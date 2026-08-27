"""Application-URL and job-active verification.

We only ever check URLs we already hold. Nothing here bypasses a login,
CAPTCHA or rate limit; a page we cannot read is reported as unreachable
rather than guessed.
"""

import logging
import re
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
}

# Phrases ATS pages show when a requisition is closed.
_CLOSED_PATTERNS = [
    r'no longer accepting applications',
    r'this (?:job|position|role|requisition) (?:is|has been) (?:closed|filled|expired)',
    r'job (?:posting )?(?:not found|no longer available|has expired)',
    r'position (?:is )?no longer (?:available|open)',
    r'we are no longer accepting',
    r'this posting (?:is|has) (?:closed|expired)',
]

VERIFIED = 'verified'
DEAD = 'dead'
UNREACHABLE = 'unreachable'


def verify_url(url, timeout=10, session=None):
    """Check a single application URL.

    Returns a dict: {url_status, verification_status, http_status, detail}
    """
    if not url:
        return {
            'url_status': 'unknown',
            'verification_status': 'unverified',
            'http_status': None,
            'detail': 'No application URL stored',
        }

    http = session or requests
    try:
        response = http.get(url, headers=_HEADERS, timeout=timeout,
                            allow_redirects=True)
    except requests.exceptions.SSLError:
        try:
            response = http.get(url, headers=_HEADERS, timeout=timeout,
                                allow_redirects=True, verify=False)
        except Exception as exc:
            return _unreachable(str(exc))
    except Exception as exc:
        return _unreachable(str(exc))

    status = response.status_code
    if status in (404, 410):
        return {
            'url_status': DEAD,
            'verification_status': 'expired',
            'http_status': status,
            'detail': f'HTTP {status} — page no longer exists',
        }
    if status in (401, 403, 429):
        # Access-controlled or rate-limited: not evidence the job is gone.
        return {
            'url_status': 'unverified',
            'verification_status': 'unreachable',
            'http_status': status,
            'detail': f'HTTP {status} — could not read the page',
        }
    if status >= 500:
        return _unreachable(f'HTTP {status} — server error', status)

    body = ''
    try:
        body = (response.text or '')[:200000].lower()
    except Exception:
        body = ''

    for pattern in _CLOSED_PATTERNS:
        match = re.search(pattern, body)
        if match:
            return {
                'url_status': DEAD,
                'verification_status': 'expired',
                'http_status': status,
                'detail': f'Page says: "{match.group(0)}"',
            }

    return {
        'url_status': VERIFIED,
        'verification_status': 'active',
        'http_status': status,
        'detail': f'HTTP {status} — page reachable, no closure notice found',
    }


def _unreachable(detail, status=None):
    return {
        'url_status': 'unverified',
        'verification_status': UNREACHABLE,
        'http_status': status,
        'detail': detail,
    }


def apply_verification(job, result):
    """Write a verification result onto a Job model instance."""
    now = datetime.now(timezone.utc)
    job.application_url_status = result['url_status']
    job.verification_status = result['verification_status']
    job.application_url_checked_at = now
    job.last_verified_at = now
    if result['verification_status'] == 'expired':
        job.is_expired = True
    return job
