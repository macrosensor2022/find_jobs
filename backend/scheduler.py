"""Daily search scheduler.

Uses APScheduler when available and falls back to a plain daemon thread so the
app never fails to start because of a missing optional dependency. The job runs
inside the Flask app context and reuses the same scrape path as the UI button,
so there is exactly one code path for "run a search".
"""

import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_scheduler = None
_fallback_thread = None
_stop_event = threading.Event()


def _load_schedule(Preference, Config):
    """Resolve schedule settings.

    Precedence, applied per key:

        explicit environment variable  >  stored DB preference  >  code default

    The stored preference used to win unconditionally. It is seeded once on
    first run, so after that editing ``SCHEDULE_ENABLED`` in ``.env`` had no
    effect at all — the value was read, then silently overwritten by the row.

    Environment now wins where it was explicitly set, which keeps ``.env`` an
    honest contract while leaving every unset key editable from the UI.
    """
    defaults = {
        'enabled': Config.SCHEDULE_ENABLED,
        'mode': Config.SCHEDULE_MODE,
        'hour': Config.SCHEDULE_HOUR,
        'minute': Config.SCHEDULE_MINUTE,
        'interval_hours': Config.SCHEDULE_INTERVAL_HOURS,
        'timezone': Config.SCHEDULE_TIMEZONE,
        'sources': list(Config.DAILY_SOURCES),
    }
    env_keys = getattr(Config, 'SCHEDULE_ENV_KEYS', {})
    overridden = []
    try:
        row = Preference.query.filter_by(key='schedule').first()
        if row and isinstance(row.parsed, dict):
            for key, value in row.parsed.items():
                if value is None:
                    continue
                env_name = env_keys.get(key)
                if env_name and Config.env_overrides(env_name):
                    overridden.append(env_name)
                    continue
                defaults[key] = value
    except Exception:
        logger.debug('Could not read schedule preference; using defaults')
    if overridden:
        logger.info(
            'Schedule: environment overrides stored preference for %s',
            ', '.join(sorted(set(overridden))),
        )
    return defaults


def _next_daily_after(now, hour, minute):
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _timezone(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        logger.warning('Unknown timezone %r; scheduling in UTC', name)
        from datetime import timezone as _tz
        return _tz.utc


def run_daily_search(app, trigger='scheduled'):
    """Execute one full scheduled run: scrape, verify, notify.

    Claims the same process-wide scrape slot the "Run search now" button uses.
    A scheduled tick that lands mid-scrape is skipped rather than queued —
    running the same sources twice minutes apart finds nothing the first run
    did not, and two writers on one SQLite file is how the lock errors start.
    """
    from backend import scrape_state

    with app.app_context():
        from backend.models import (
            Application, Job, Notification, Preference, WatchlistCompany, db,
        )
        from config.settings import Config
        from scrapers.job_scraper_manager import JobScraperManager
        from services.notifications import generate_notifications

        schedule = _load_schedule(Preference, Config)
        sources = schedule.get('sources') or list(Config.DAILY_SOURCES)
        keywords = Config.SEARCH_KEYWORDS[:12]

        try:
            scrape_state.begin(trigger=trigger, sources=sources,
                               params={'sources': sources, 'keywords': keywords})
        except scrape_state.ScrapeInProgress as busy:
            logger.info(
                'SCRAPE SKIPPED — a %s scrape started at %s is still running',
                busy.state.get('trigger'), busy.state.get('started_at'),
            )
            return {'skipped': True, 'reason': 'scrape already running'}

        logger.info('SCRAPE START (%s): %s', trigger, sources)
        results = {}
        try:
            manager = JobScraperManager(
                db.session, min_match_score=25,
                progress_callback=scrape_state.update_progress,
            )
            results = manager.scrape_all(
                sources=sources,
                keywords=keywords,
                locations=Config.TARGET_LOCATIONS,
                trigger=trigger,
            )
        except Exception as exc:
            logger.exception('Scheduled search failed')
            try:
                db.session.rollback()
            except Exception:
                pass
            scrape_state.fail(exc)
            return {'error': str(exc)}

        # Verify application URLs for top ranked jobs (never invents URLs)
        try:
            from services.batch_verify import verify_top_jobs
            verify_summary = verify_top_jobs(
                Job, session=db.session,
                limit=int(getattr(Config, 'VERIFY_TOP_N', 25)),
            )
            results['verify'] = {
                k: verify_summary.get(k)
                for k in ('checked', 'verified', 'dead', 'blocked',
                          'redirected', 'unreachable', 'unknown')
            }
        except Exception:
            logger.exception('Batch URL verification failed')
            try:
                db.session.rollback()
            except Exception:
                pass

        try:
            created = generate_notifications(
                db, Job, Application, Notification, WatchlistCompany,
            )
            logger.info('Scheduled search created %d notifications', created)
        except Exception:
            logger.exception('Notification generation failed')
            try:
                db.session.rollback()
            except Exception:
                pass

        scrape_state.finish(
            results,
            message=(
                f"Scheduled run done — {results.get('total_new_jobs', 0)} new jobs"
            ),
            sources_total=len(sources),
        )
        logger.info(
            'SCRAPE COMPLETE (%s): %s new jobs',
            trigger, results.get('total_new_jobs', 0),
        )
        return results


def start(app):
    """Start the scheduler. Idempotent — a second call is a no-op.

    Flask's reloader and any accidental second ``start()`` would otherwise
    create a second scheduler, and two schedulers means two scrapes per tick.
    """
    global _scheduler, _fallback_thread

    from backend.models import Preference
    from config.settings import Config

    if _scheduler is not None or (
        _fallback_thread is not None and _fallback_thread.is_alive()
    ):
        logger.info('Scheduler already running; not starting a second one')
        return _scheduler or _fallback_thread

    with app.app_context():
        schedule = _load_schedule(Preference, Config)

    if not schedule.get('enabled'):
        logger.info('Search scheduler disabled by configuration')
        return None

    mode = schedule.get('mode', Config.SCHEDULE_MODE)
    hour = int(schedule.get('hour', 7))
    minute = int(schedule.get('minute', 0))
    interval_hours = float(schedule.get('interval_hours', '3') or 3)
    tz_name = schedule.get('timezone', 'America/New_York')

    if mode == 'daily':
        sch_desc = 'daily at %02d:%02d %s' % (hour, minute, tz_name)
    else:
        sch_desc = 'every %.2g hours (%s)' % (interval_hours, tz_name)

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(timezone=_timezone(tz_name))
        if mode == 'daily':
            _scheduler.add_job(
                lambda: run_daily_search(app),
                trigger='cron', hour=hour, minute=minute,
                id='search_feed', replace_existing=True,
                misfire_grace_time=3600, coalesce=True, max_instances=1,
            )
        else:
            _scheduler.add_job(
                lambda: run_daily_search(app),
                trigger='interval', hours=interval_hours,
                id='search_feed', replace_existing=True,
                misfire_grace_time=3600, coalesce=True, max_instances=1,
            )
        _scheduler.start()
        logger.info('Scheduler started via APScheduler for %s', sch_desc)
        return _scheduler
    except ImportError:
        logger.info('APScheduler not installed; using the built-in timer thread')

    tzinfo = _timezone(tz_name)

    def _loop():
        while not _stop_event.is_set():
            now = datetime.now(tzinfo)
            if mode == 'daily':
                target = _next_daily_after(now, hour, minute)
                desc = 'daily search at %02d:%02d' % (hour, minute)
            else:
                target = now + timedelta(hours=interval_hours)
                desc = 'search every %.2gh' % interval_hours
            wait_seconds = (target - now).total_seconds()
            logger.info('Next search in %.1f hours (%s)', wait_seconds / 3600, desc)
            if _stop_event.wait(wait_seconds):
                return
            try:
                run_daily_search(app)
            except Exception:
                logger.exception('Scheduled search crashed')
            # Avoid tight re-triggering immediately after a run.
            time.sleep(61)

    _fallback_thread = threading.Thread(
        target=_loop, daemon=True, name='daily-search-scheduler',
    )
    _fallback_thread.start()
    logger.info(
        'Daily scheduler thread started for %s', sch_desc
    )
    return _fallback_thread


def next_run_time():
    if _scheduler is not None:
        job = _scheduler.get_job('search_feed')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    return None


def status():
    """What the Scheduler panel needs: is it up, when did it last run, did it fail.

    Last-run facts come from the shared scrape state, so a scheduled run and a
    manual run report through the same fields.
    """
    from backend import scrape_state

    snapshot = scrape_state.snapshot()
    if _scheduler is not None:
        backend = 'apscheduler'
        running = _scheduler.running
    elif _fallback_thread is not None:
        backend = 'timer-thread'
        running = _fallback_thread.is_alive()
    else:
        backend, running = None, False

    return {
        'running': running,
        'backend': backend,
        'next_run_at': next_run_time(),
        'scrape_in_progress': snapshot['status'] == 'running',
        'current_trigger': snapshot.get('trigger'),
        'last_run_at': snapshot.get('last_completed_at'),
        'last_run_status': snapshot.get('last_status'),
        'last_run_trigger': snapshot.get('last_trigger'),
        'last_run_new_jobs': snapshot.get('last_new_jobs'),
        'last_run_error': snapshot.get('last_error'),
        # The scheduler lives inside the Flask process. Closing the terminal
        # that runs `python run.py` stops it; nothing runs while the app is down.
        'requires_app_running': True,
    }


def stop():
    """Shut down cleanly so Ctrl+C does not leave a thread behind."""
    global _scheduler, _fallback_thread

    _stop_event.set()
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            logger.debug('Scheduler shutdown raised', exc_info=True)
        _scheduler = None
    if _fallback_thread is not None:
        # Daemon thread; the stop event releases it from its wait().
        _fallback_thread = None
    _stop_event.clear()
