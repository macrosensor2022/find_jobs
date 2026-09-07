"""Process-wide scrape coordination.

There are two ways a scrape starts — the "Run search now" button and the
scheduler — and they used to guard themselves independently. The API had a
lock, the scheduler had none, so a scheduled run firing during a manual scrape
gave two threads writing SQLite at once.

Both paths go through :func:`begin` now. Only one scrape runs at a time; the
loser is told so rather than queued, because two scrapes of the same sources
minutes apart produce nothing the first one did not.

This module holds no database handle and imports nothing from the app, so
either side can import it without a cycle.
"""

import copy
import threading
from datetime import datetime, timezone


class ScrapeInProgress(RuntimeError):
    """Raised when a scrape is asked for while one is already running."""

    def __init__(self, state):
        super().__init__('A scrape is already running')
        self.state = state


_lock = threading.Lock()
_state = {
    'status': 'idle',  # idle | running | completed | failed | skipped
    'message': '',
    'trigger': None,
    'started_at': None,
    'completed_at': None,
    'progress': {},
    'results': None,
    'error': None,
    'params': None,
    'last_completed_at': None,
    'last_status': None,
    'last_error': None,
    'last_new_jobs': None,
    'last_trigger': None,
}


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def is_running():
    with _lock:
        return _state['status'] == 'running'


def begin(trigger='manual', params=None, sources=None):
    """Claim the scrape slot. Raises :class:`ScrapeInProgress` if taken."""
    with _lock:
        if _state['status'] == 'running':
            raise ScrapeInProgress(_snapshot())
        _state.update({
            'status': 'running',
            'message': 'Starting scrape…',
            'trigger': trigger,
            'started_at': _utcnow_iso(),
            'completed_at': None,
            'progress': {
                'current_source': None,
                'sources_done': [],
                'sources_total': len(sources or []),
                'total_new_jobs': 0,
                'total_matched_jobs': 0,
            },
            'results': None,
            'error': None,
            'params': params,
        })
        return _snapshot()


def update_progress(info):
    """Merge a progress payload from the running scrape."""
    if not info:
        return
    with _lock:
        progress = dict(_state.get('progress') or {})
        progress.update(info)
        _state['progress'] = progress
        if info.get('message'):
            _state['message'] = info['message']
        if info.get('partial_results'):
            _state['results'] = copy.deepcopy(info['partial_results'])


def finish(results=None, message=None, sources_total=None):
    with _lock:
        _state.update({
            'status': 'completed',
            'results': results,
            'completed_at': _utcnow_iso(),
            'message': message or 'Scrape complete',
            'last_completed_at': _utcnow_iso(),
            'last_status': 'completed',
            'last_error': None,
            'last_new_jobs': (results or {}).get('total_new_jobs'),
            'last_trigger': _state.get('trigger'),
        })
        progress = dict(_state.get('progress') or {})
        progress.update({
            'current_source': None,
            'sources_done': list(((results or {}).get('sources') or {}).keys()),
            'total_new_jobs': (results or {}).get('total_new_jobs', 0),
            'total_matched_jobs': (results or {}).get('total_matched_jobs', 0),
        })
        if sources_total is not None:
            progress['sources_total'] = sources_total
        _state['progress'] = progress
        return _snapshot()


def fail(error):
    with _lock:
        _state.update({
            'status': 'failed',
            'error': str(error),
            'completed_at': _utcnow_iso(),
            'message': f'Scrape failed: {error}',
            'last_completed_at': _utcnow_iso(),
            'last_status': 'failed',
            'last_error': str(error),
            'last_trigger': _state.get('trigger'),
        })
        return _snapshot()


def _snapshot():
    """Caller-safe copy. Must be called with the lock held."""
    return {
        'status': _state['status'],
        'message': _state['message'],
        'trigger': _state['trigger'],
        'started_at': _state['started_at'],
        'completed_at': _state['completed_at'],
        'progress': dict(_state.get('progress') or {}),
        'error': _state.get('error'),
        'results': _state.get('results'),
        'last_completed_at': _state.get('last_completed_at'),
        'last_status': _state.get('last_status'),
        'last_error': _state.get('last_error'),
        'last_new_jobs': _state.get('last_new_jobs'),
        'last_trigger': _state.get('last_trigger'),
    }


def snapshot():
    with _lock:
        return _snapshot()
