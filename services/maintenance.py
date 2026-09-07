"""Derived-field maintenance.

Freshness is a function of *now* and the source posting date, so any value
stored in a column is correct only at the instant it was written. Left alone,
a job scored two weeks ago keeps claiming ``freshness_bucket = 'fresh'``
forever.

Two mechanisms keep that honest:

* :func:`refresh_freshness` — one set-based UPDATE that recomputes
  ``freshness_hours`` / ``freshness_bucket`` / ``is_expired`` from
  ``date_posted``. Cheap enough to run at startup, after every scrape, and on
  every scheduler tick, which is exactly what the app does.
* ``Job.to_dict`` recomputes the same values on read, so the UI is correct even
  between refreshes.

Both derive from ``date_posted`` only. Scrape time and rediscovery time never
stand in for a posting date.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from config.settings import Config
from services.freshness import bucket_for

logger = logging.getLogger(__name__)


_LABEL_RE = re.compile(r'^[a-z_]{1,16}$')


def _bucket_case_sql():
    """Build the CASE expression mapping age-in-hours to a bucket label.

    The labels and thresholds are inlined rather than bound, because SQLite
    cannot parameterize a CASE arm. They come from ``Config.FRESHNESS_BUCKETS``
    (code, not user input), but they are validated anyway so a hand-edited
    config can never turn this into a SQL-injection surface: thresholds must be
    numeric and labels must be plain lowercase identifiers.
    """
    whens = []
    default = 'stale'
    for threshold, label in Config.FRESHNESS_BUCKETS:
        if not _LABEL_RE.match(str(label)):
            raise ValueError(
                f'Invalid freshness bucket label {label!r}: '
                'expected lowercase letters/underscores only'
            )
        if threshold is None:
            default = label
            continue
        whens.append(f"WHEN age_h < {float(threshold)} THEN '{label}'")
    return ' '.join(whens), default


def refresh_freshness(session, now=None):
    """Recompute freshness columns from ``date_posted`` for every stored job.

    Returns a dict of counts. Jobs with no known posting date get NULL
    freshness (rendered as "Posting date unknown") and are never auto-expired —
    an unknown date is not evidence that a posting is old.
    """
    now = now or datetime.now(timezone.utc)
    whens, default = _bucket_case_sql()
    max_age_hours = float(Config.MAX_JOB_AGE_DAYS) * 24.0

    # julianday() differences are in days; ×24 gives hours. Clamped at 0 so a
    # posting date slightly in the future (timezone skew at the source) reads
    # as brand new rather than negative.
    age_expr = (
        "MAX(0.0, (julianday(:now) - julianday(date_posted)) * 24.0)"
    )
    sql = text(f"""
        UPDATE jobs
           SET freshness_hours  = CAST({age_expr} AS INTEGER),
               freshness_bucket = (
                   SELECT CASE {whens} ELSE '{default}' END
                     FROM (SELECT {age_expr} AS age_h)
               ),
               is_expired = CASE
                   WHEN is_applied = 1 THEN is_expired
                   WHEN {age_expr} > {max_age_hours} THEN 1
                   ELSE 0
               END
         WHERE date_posted IS NOT NULL
    """)
    unknown_sql = text("""
        UPDATE jobs
           SET freshness_hours = NULL,
               freshness_bucket = NULL
         WHERE date_posted IS NULL
    """)

    iso_now = now.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
    updated = session.execute(sql, {'now': iso_now}).rowcount
    unknown = session.execute(unknown_sql).rowcount
    session.commit()
    logger.info(
        'FRESHNESS REFRESH complete: %s dated jobs recomputed, %s with unknown date',
        updated, unknown,
    )
    return {'refreshed': updated or 0, 'unknown_date': unknown or 0}


def backfill_seen_timestamps(session):
    """Give older rows the discovery timestamps the pipeline now relies on.

    ``date_scraped`` was historically bumped on every rediscovery, so it is the
    best available approximation of both first and last sighting for legacy
    rows. New rows set ``first_seen``/``last_seen`` explicitly and
    ``date_scraped`` never moves again.
    """
    first = session.execute(text(
        'UPDATE jobs SET first_seen = COALESCE(date_scraped, created_at) '
        'WHERE first_seen IS NULL'
    )).rowcount
    last = session.execute(text(
        'UPDATE jobs SET last_seen = COALESCE(first_seen, date_scraped, created_at) '
        'WHERE last_seen IS NULL'
    )).rowcount
    session.commit()
    if first or last:
        logger.info(
            'Backfilled discovery timestamps: first_seen=%s last_seen=%s', first, last
        )
    return {'first_seen': first or 0, 'last_seen': last or 0}


def age_cutoff(days, now=None):
    """UTC datetime `days` before now, for `date_posted >= cutoff` filters."""
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=days)


def live_freshness(date_posted, now=None):
    """Bucket + hours computed right now, for read paths.

    Returns ``(hours, bucket)``; both are ``None`` when the posting date is
    unknown, which the UI renders as "Posting date unknown".
    """
    if date_posted is None:
        return None, None
    posted = date_posted
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = max(0, int((now - posted).total_seconds() / 3600.0))
    return hours, bucket_for(hours)
