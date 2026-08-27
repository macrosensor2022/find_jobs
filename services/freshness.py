"""Freshness computation. Never invents a posting date."""

from datetime import datetime, timedelta, timezone

from config.settings import Config

BUCKET_LABELS = {
    'hot': 'Posted in the last 24 hours',
    'fresh': 'Posted 1-3 days ago',
    'recent': 'Posted 4-7 days ago',
    'aging': 'Posted 8-14 days ago',
    'stale': 'Posted more than 14 days ago',
    'unknown': 'Posting date unknown',
}

_BUCKET_SCORE = {
    'hot': 100.0,
    'fresh': 85.0,
    'recent': 65.0,
    'aging': 40.0,
    'stale': 15.0,
    'unknown': 45.0,
}


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def age_hours(date_posted, now=None):
    """Hours since posting, or None when the posting date is unknown."""
    posted = _as_utc(date_posted)
    if posted is None:
        return None
    now = _as_utc(now) or datetime.now(timezone.utc)
    delta = (now - posted).total_seconds() / 3600.0
    return max(0, int(delta))


def bucket_for(hours):
    if hours is None:
        return 'unknown'
    for threshold, label in Config.FRESHNESS_BUCKETS:
        if threshold is None or hours < threshold:
            return label
    return 'stale'


def evaluate(date_posted, now=None):
    hours = age_hours(date_posted, now)
    bucket = bucket_for(hours)
    return {
        'hours': hours,
        'bucket': bucket,
        'label': BUCKET_LABELS[bucket],
        'score': _BUCKET_SCORE[bucket],
        'is_known': hours is not None,
    }


def is_expired(date_posted, expiry_days=None, now=None):
    """Age-based expiry. Unknown dates are never auto-expired."""
    expiry_days = expiry_days or Config.JOB_EXPIRY_DAYS
    hours = age_hours(date_posted, now)
    if hours is None:
        return False
    return hours > expiry_days * 24


def needs_reverification(last_verified_at, now=None):
    if last_verified_at is None:
        return True
    now = _as_utc(now) or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=Config.VERIFY_STALE_AFTER_HOURS)
    return _as_utc(last_verified_at) < cutoff
