"""Batch verification of application URLs for top-ranked jobs.

Never invents URLs — only checks URLs already stored on Job rows.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from config.settings import Config
from services.briefing import applyable_query
from services.freshness import needs_reverification
from services.verification import apply_verification, verify_url

logger = logging.getLogger(__name__)


def select_jobs_to_verify(Job, limit: int = None, include_stale: bool = True) -> List:
    """Pick top realistic jobs that need a live URL check."""
    limit = limit or int(getattr(Config, 'VERIFY_TOP_N', 15))
    query = applyable_query(Job, realistic=True).filter(
        Job.application_url.isnot(None),
        Job.application_url != '',
    ).order_by(
        Job.final_score.desc().nullslast(),
        Job.candidate_match_score.desc().nullslast(),
    ).limit(max(limit * 3, limit))

    selected = []
    for job in query.all():
        status = (job.application_url_status or 'unknown').lower()
        if status == 'verified' and not (
            include_stale and needs_reverification(job.last_verified_at)
        ):
            continue
        if status == 'dead':
            continue
        selected.append(job)
        if len(selected) >= limit:
            break
    return selected


def verify_jobs(jobs: Iterable, session=None, commit_every: int = 5) -> dict:
    """Verify a list of Job models. Returns a summary dict."""
    summary = {
        'checked': 0,
        'verified': 0,
        'dead': 0,
        'unreachable': 0,
        'unknown': 0,
        'details': [],
    }
    pending = 0
    for job in jobs:
        url = job.application_url or job.job_url
        if not url:
            summary['unknown'] += 1
            continue
        result = verify_url(url)
        apply_verification(job, result)
        summary['checked'] += 1
        status = result.get('url_status') or 'unknown'
        if status == 'verified':
            summary['verified'] += 1
        elif status == 'dead':
            summary['dead'] += 1
        elif status == 'unverified':
            summary['unreachable'] += 1
        else:
            summary['unknown'] += 1
        summary['details'].append({
            'job_id': job.id,
            'title': job.title,
            'url_status': status,
            'verification_status': result.get('verification_status'),
            'detail': result.get('detail'),
        })
        pending += 1
        if session is not None and pending >= commit_every:
            try:
                session.commit()
            except Exception:
                logger.exception('Commit during batch verify failed')
                try:
                    session.rollback()
                except Exception:
                    pass
            pending = 0

    if session is not None and pending:
        try:
            session.commit()
        except Exception:
            logger.exception('Final commit during batch verify failed')
            try:
                session.rollback()
            except Exception:
                pass

    logger.info(
        'Batch verify: checked=%s verified=%s dead=%s unreachable=%s',
        summary['checked'], summary['verified'], summary['dead'], summary['unreachable'],
    )
    return summary


def verify_top_jobs(Job, session=None, limit: Optional[int] = None) -> dict:
    jobs = select_jobs_to_verify(Job, limit=limit)
    return verify_jobs(jobs, session=session)
