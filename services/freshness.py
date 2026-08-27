"""Freshness computation. Never invents a posting date."""

from datetime import datetime, timedelta, timezone

from config.settings import Config

BUCKET_LABELS = {
    'hot': 'Posted in the last 6 hours',
    'fresh': 'Posted 6-24 hours ago',
    'recent': 'Posted 1-3 days ago',
    'aging': 'Posted 3-7 days ago',
    'old': 'Posted 7-14 days ago',
    'stale': 'Posted more than 14 days ago',
    'unknown': 'Posting date unknown',
}

_BUCKET_SCORE = {
    'hot': 100.0,
    'fresh': 90.0,
    'recent': 72.0,
    'aging': 50.0,
    'old': 35.0,
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


def human_age(date_value, now=None):
    """Human-readable age like '3h 21m ago', or None when unknown."""
    if date_value is None:
        return None
    now = _as_utc(now) or datetime.now(timezone.utc)
    dt = _as_utc(date_value)
    if dt is None:
        return None
    seconds = max(0, int((now - dt).total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        return f'{days}d {hours}h ago'
    if hours >= 1:
        return f'{hours}h {minutes}m ago'
    if minutes >= 1:
        return f'{minutes}m ago'
    return 'just now'


def display_age(date_posted, date_scraped, now=None):
    """Present posting age, falling back to discovery time only when the
    posting time is unknown. Never conflates the two: the label states which
    one is being reported."""
    if date_posted is not None and _as_utc(date_posted) is not None:
        return {
            'text': human_age(date_posted, now),
            'basis': 'posted',
            'bucket': bucket_for(age_hours(date_posted, now)),
        }
    if date_scraped is not None and _as_utc(date_scraped) is not None:
        return {
            'text': f'First discovered {human_age(date_scraped, now)}',
            'basis': 'discovered',
            'bucket': bucket_for(age_hours(date_scraped, now)) or 'unknown',
        }
    return {'text': 'Date unknown', 'basis': 'unknown', 'bucket': 'unknown'}


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
