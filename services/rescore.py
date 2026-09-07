"""One rescoring path, shared by the CLI script, startup, and the scheduler.

There used to be three partial versions of this: the scrape pipeline enriched
new jobs with industry/contact/golden data, ``scripts/rescore_all.py`` applied
only the core score, and the startup task touched only rows with
``final_score IS NULL``. The result was a table where most rows had a final
score but no ``application_recommendation``, ``industry`` or
``golden_opportunity_score``, so the UI rendered blanks for jobs that were
scored perfectly well.

Everything routes through :func:`rescore_job` now. It never invents data: each
field is derived from the job's own stored text, dates and URL status.
"""

import json
import logging

from config.settings import Config
from services.dedupe import build_dedupe_key
from services.freshness import is_expired
from services.ranking import apply_to_model, score_job

logger = logging.getLogger(__name__)


def job_payload(job):
    """The scoring engine's view of a stored Job row."""
    return {
        'title': job.title,
        'company': job.company,
        'location': job.location,
        'description': job.description,
        'source': job.source,
        'date_posted': job.date_posted,
        'is_remote': job.is_remote,
        'worksite_state': job.worksite_state,
        'salary_min': job.salary_min,
        'salary_max': job.salary_max,
        'salary_predicted': job.salary_predicted,
        'description_partial': job.description_partial,
        'application_url': job.application_url or job.job_url,
        'application_url_status': job.application_url_status,
        'verification_status': job.verification_status,
        'is_expired': job.is_expired,
        'duplicate_of_id': job.duplicate_of_id,
        'competition_score': job.competition_score,
        'competition_signal': job.competition_signal,
        'industry_opportunity_score': job.industry_opportunity_score,
    }


def needs_rescore(job):
    """True when a row is missing any field the current engine produces."""
    return (
        job.final_score is None
        or job.application_recommendation is None
        or job.application_priority_score is None
        or job.golden_opportunity_score is None
        or job.industry is None
        or job.role_tier is None and not job.role_blocked
    )


def classify_industry_for(job):
    """Industry classification from the job's own text. Best-effort."""
    from services.industry import classify_industry

    try:
        result = classify_industry(
            title=job.title, description=job.description,
            company=job.company, source=job.source,
        )
    except Exception:
        logger.debug('Industry classification failed for job %s', job.id, exc_info=True)
        return False
    job.industry = result['industry']
    job.industry_label = result['label']
    job.under_the_radar = result['under_the_radar']
    job.industry_evidence = json.dumps(result['evidence'])
    return True


def refresh_industry_opportunity(session, Job, job):
    from services.industry import industry_opportunity

    if not job.industry:
        return
    try:
        opp = industry_opportunity(session, Job, job.industry)
        job.industry_opportunity = opp['opportunity']
        job.industry_opportunity_score = opp['opportunity_score']
    except Exception:
        logger.debug('Industry opportunity refresh failed for job %s',
                     job.id, exc_info=True)


def rescore_job(job, watchlist=None, location_prefs=None,
                session=None, Job=None, with_industry=True):
    """Rescore one stored job in place. Returns the scoring result."""
    job.is_expired = is_expired(job.date_posted)
    job.dedupe_key = job.dedupe_key or build_dedupe_key(job)

    if with_industry and session is not None and Job is not None:
        # Classify before scoring so the golden composite sees the industry
        # opportunity score rather than recomputing without it.
        classify_industry_for(job)
        refresh_industry_opportunity(session, Job, job)

    result = score_job(
        job_payload(job), watchlist=watchlist, location_prefs=location_prefs,
    )
    apply_to_model(job, result)

    # Rows stored before provenance existed keep the real source URL in
    # job_url. Promote it, labelled unverified — never construct a URL.
    if not job.application_url and job.job_url:
        job.application_url = job.job_url
        job.application_url_status = job.application_url_status or 'unverified'

    if result['match']['eligible']:
        if job.is_hidden and not job.is_applied and not job.is_favorite:
            job.is_hidden = False
    else:
        job.is_hidden = True

    return result


def load_watchlist(WatchlistCompany):
    try:
        rows = WatchlistCompany.query.filter_by(is_active=True).all()
    except Exception:
        rows = []
    if rows:
        return [{'name': r.name, 'priority': r.priority} for r in rows]
    return [{'name': n, 'priority': 2} for n in Config.WATCHLIST_COMPANIES]


def load_location_prefs(Preference):
    try:
        row = Preference.query.filter_by(key='location_preferences').first()
    except Exception:
        return None
    if row and isinstance(row.parsed, dict):
        return row.parsed
    return None


def rescore_jobs(session, models, jobs, batch=200, with_industry=True,
                 progress=None):
    """Rescore a list of jobs, committing in batches. Returns counts."""
    watchlist = load_watchlist(models['WatchlistCompany'])
    location_prefs = load_location_prefs(models['Preference'])
    Job = models['Job']

    stats = {'scored': 0, 'eligible': 0, 'hidden': 0, 'failed': 0}
    for index, job in enumerate(jobs, start=1):
        try:
            result = rescore_job(
                job, watchlist=watchlist, location_prefs=location_prefs,
                session=session, Job=Job, with_industry=with_industry,
            )
            stats['scored'] += 1
            if result['match']['eligible']:
                stats['eligible'] += 1
            else:
                stats['hidden'] += 1
        except Exception as exc:
            # One bad row must never stop a rescore of thousands.
            stats['failed'] += 1
            logger.warning('Rescore failed for job %s: %s', getattr(job, 'id', '?'), exc)
        if index % batch == 0:
            session.commit()
            if progress:
                progress(index, len(jobs))
    session.commit()
    logger.info('RESCORE COMPLETE %s', stats)
    return stats
