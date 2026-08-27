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
    """Schedule settings from the DB, falling back to config defaults."""
    defaults = {
        'enabled': Config.SCHEDULE_ENABLED,
        'hour': Config.SCHEDULE_HOUR,
        'minute': Config.SCHEDULE_MINUTE,
        'timezone': Config.SCHEDULE_TIMEZONE,
        'sources': list(Config.DAILY_SOURCES),
    }
    try:
        row = Preference.query.filter_by(key='schedule').first()
        if row and isinstance(row.parsed, dict):
            defaults.update({k: v for k, v in row.parsed.items() if v is not None})
    except Exception:
        logger.debug('Could not read schedule preference; using defaults')
    return defaults


def _timezone(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        logger.warning('Unknown timezone %r; scheduling in UTC', name)
        from datetime import timezone as _tz
        return _tz.utc


def run_daily_search(app, trigger='scheduled'):
    """Execute one full daily run: scrape, then notifications."""
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

        logger.info('Daily search starting (%s): %s', trigger, sources)
        results = {}
        try:
            manager = JobScraperManager(db.session, min_match_score=25)
            results = manager.scrape_all(
                sources=sources,
                keywords=keywords,
                locations=Config.TARGET_LOCATIONS,
                trigger=trigger,
            )
        except Exception:
            logger.exception('Daily search failed')
            try:
                db.session.rollback()
            except Exception:
                pass

        # Verify application URLs for top ranked jobs (never invents URLs)
        try:
            from services.batch_verify import verify_top_jobs
            verify_summary = verify_top_jobs(
                Job, session=db.session,
                limit=int(getattr(Config, 'VERIFY_TOP_N', 15)),
            )
            results['verify'] = {
                k: verify_summary[k]
                for k in ('checked', 'verified', 'dead', 'unreachable', 'unknown')
            }
            logger.info('Daily verify: %s', results['verify'])
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
            logger.info('Daily search created %d notifications', created)
        except Exception:
            logger.exception('Notification generation failed')
            try:
                db.session.rollback()
            except Exception:
                pass

        logger.info(
            'Daily search finished: %s new jobs',
            results.get('total_new_jobs', 0),
        )
        return results


def start(app):
    """Start the scheduler. Safe to call once at startup."""
    global _scheduler, _fallback_thread

    from backend.models import Preference
    from config.settings import Config

    with app.app_context():
        schedule = _load_schedule(Preference, Config)

    if not schedule.get('enabled'):
        logger.info('Daily scheduler disabled by configuration')
        return None

    hour = int(schedule.get('hour', 7))
    minute = int(schedule.get('minute', 0))
    tz_name = schedule.get('timezone', 'America/New_York')

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(timezone=_timezone(tz_name))
        _scheduler.add_job(
            lambda: run_daily_search(app),
            trigger='cron', hour=hour, minute=minute,
            id='daily_search', replace_existing=True,
            misfire_grace_time=3600, coalesce=True, max_instances=1,
        )
        _scheduler.start()
        logger.info(
            'Daily scheduler started via APScheduler for %02d:%02d %s',
            hour, minute, tz_name,
        )
        return _scheduler
    except ImportError:
        logger.info('APScheduler not installed; using the built-in timer thread')

    tzinfo = _timezone(tz_name)

    def _loop():
        while not _stop_event.is_set():
            now = datetime.now(tzinfo)
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info('Next daily search in %.1f hours', wait_seconds / 3600)
            if _stop_event.wait(wait_seconds):
                return
            try:
                run_daily_search(app)
            except Exception:
                logger.exception('Scheduled daily search crashed')
            # Guard against clock skew re-triggering within the same minute.
            time.sleep(61)

    _fallback_thread = threading.Thread(
        target=_loop, daemon=True, name='daily-search-scheduler',
    )
    _fallback_thread.start()
    logger.info(
        'Daily scheduler thread started for %02d:%02d %s', hour, minute, tz_name,
    )
    return _fallback_thread


def next_run_time():
    if _scheduler is not None:
        job = _scheduler.get_job('daily_search')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    return None


def stop():
    _stop_event.set()
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
