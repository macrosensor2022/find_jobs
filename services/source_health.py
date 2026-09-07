"""Source enablement and health reporting.

Two rules drive this module:

1. A source that cannot run (switched off, or missing credentials) is reported
   as ``disabled`` with the reason. It is never reported as "succeeded with
   0 jobs" — that would hide a configuration gap behind a legitimate-looking
   empty result.
2. A source that ran and genuinely found nothing is reported as ``success``
   with ``jobs_discovered == 0``. That is a real answer, not a failure.

Nothing here reads or returns secret values; only whether a credential is
present.
"""

from datetime import datetime, timezone

from config.settings import Config

# Terminal statuses a SourceRun can carry.
STATUS_SUCCESS = 'success'
STATUS_EMPTY = 'empty'        # ran fine, source legitimately had nothing
STATUS_FAILED = 'failed'
STATUS_DISABLED = 'disabled'
STATUS_RUNNING = 'running'

_HEALTHY = {STATUS_SUCCESS, STATUS_EMPTY}


def registry():
    return getattr(Config, 'SOURCE_REGISTRY', {}) or {}


def source_label(source):
    meta = registry().get(source) or {}
    return meta.get('label') or (source or '').replace('_', ' ').title()


def missing_credentials(source):
    """Names of the required config keys that are not configured.

    Returns key *names* only — never the values.
    """
    meta = registry().get(source) or {}
    missing = []
    for key in meta.get('requires') or []:
        if not (getattr(Config, key, '') or '').strip():
            missing.append(key)
    return missing


def source_status(source):
    """Resolve whether a source may run.

    Returns ``{'enabled': bool, 'reason': str|None, 'missing': [...], ...}``.
    """
    meta = registry().get(source)
    if meta is None:
        # Unknown sources are allowed through: the manager still validates that
        # an adapter exists, and we would rather surface "Unknown source" from
        # there than silently drop a source someone wired up by hand.
        return {
            'source': source, 'label': source_label(source), 'enabled': True,
            'reason': None, 'missing': [], 'kind': 'unknown',
            'signup_url': None, 'registered': False,
        }

    flag = meta.get('enable_flag')
    if flag and not getattr(Config, flag, True):
        return {
            'source': source, 'label': meta.get('label'), 'enabled': False,
            'reason': f'Turned off ({flag}=false)', 'missing': [],
            'kind': meta.get('kind'), 'signup_url': meta.get('signup_url'),
            'registered': True,
        }

    missing = missing_credentials(source)
    if missing:
        return {
            'source': source, 'label': meta.get('label'), 'enabled': False,
            'reason': 'API credentials not configured '
                      f'({", ".join(missing)} missing from .env)',
            'missing': missing, 'kind': meta.get('kind'),
            'signup_url': meta.get('signup_url'), 'registered': True,
        }

    return {
        'source': source, 'label': meta.get('label'), 'enabled': True,
        'reason': None, 'missing': [], 'kind': meta.get('kind'),
        'signup_url': meta.get('signup_url'), 'registered': True,
    }


def is_enabled(source):
    return source_status(source)['enabled']


def enabled_sources(sources):
    """Split a requested source list into (runnable, skipped_status_dicts)."""
    runnable, skipped = [], []
    for source in sources or []:
        status = source_status(source)
        (runnable if status['enabled'] else skipped).append(
            source if status['enabled'] else status
        )
    return runnable, skipped


def configured_sources():
    """Enablement snapshot for every registered source, for the Scraper page."""
    return [source_status(name) for name in sorted(registry())]


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def health_label(status, discovered, last_success_at, now=None):
    """A short, honest health verdict for one source."""
    if status == STATUS_DISABLED:
        return 'Disabled'
    if status == STATUS_FAILED:
        return 'Failing'
    if status == STATUS_RUNNING:
        return 'Running'
    if (discovered or 0) == 0:
        # Ran cleanly but returned nothing. That is only a warning if it has
        # been empty for a long time.
        now = _as_utc(now) or datetime.now(timezone.utc)
        last = _as_utc(last_success_at)
        if last is None or (now - last).total_seconds() > 7 * 86400:
            return 'No results'
        return 'Healthy'
    return 'Healthy'
