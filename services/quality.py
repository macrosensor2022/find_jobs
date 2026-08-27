"""Job quality score: how much we can trust this listing.

This exists so a scraped listing with a lucky keyword score cannot outrank a
verified employer posting.
"""

from config.settings import Config
from services.freshness import evaluate as evaluate_freshness

# Company names that some adapters synthesize from a board slug or placeholder.
_PLACEHOLDER_COMPANIES = {
    'see posting', 'unknown', 'n/a', 'na', 'confidential', 'undisclosed',
    'company', 'employer', '',
}


def evaluate_quality(job):
    """Return 0-100 quality with the specific flags that reduced it."""
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    flags = []
    score = 100.0

    if get('is_expired'):
        score -= 60.0
        flags.append('Listing is expired')
    verification = get('verification_status') or 'unverified'
    if verification == 'expired':
        score -= 60.0
        flags.append('Verified as no longer available')
    elif verification == 'unreachable':
        score -= 15.0
        flags.append('Listing page could not be reached')

    fresh = evaluate_freshness(get('date_posted'))
    if not fresh['is_known']:
        score -= 12.0
        flags.append('Posting date unknown')
    elif fresh['bucket'] == 'stale':
        score -= 10.0
        flags.append('Posting is more than 14 days old')

    url_status = get('application_url_status') or 'unknown'
    if not get('application_url'):
        score -= 25.0
        flags.append('No application URL captured')
    elif url_status == 'dead':
        score -= 40.0
        flags.append('Application URL is dead')
    elif url_status == 'search_fallback':
        score -= 20.0
        flags.append('Only a search link is available, not a real apply page')
    elif url_status == 'unknown':
        score -= 10.0
        flags.append('Application URL provenance unknown')
    elif url_status == 'unverified':
        score -= 5.0
        flags.append('Application URL not yet verified')

    company = (get('company') or '').strip().lower()
    if company in _PLACEHOLDER_COMPANIES:
        score -= 25.0
        flags.append('Employer could not be identified')

    description = get('description') or ''
    if len(description) < Config.MIN_DESCRIPTION_CHARS:
        score -= 28.0
        flags.append('Description is missing or too short to evaluate')
    elif get('description_partial'):
        score -= 8.0
        flags.append('Source returned only a partial description')

    trust = Config.SOURCE_TRUST.get(get('source') or '', 0.6)
    score -= (1.0 - trust) * 25.0
    if trust < 0.7:
        flags.append(f'Lower-trust source ({get("source")})')

    if get('duplicate_of_id'):
        score -= 30.0
        flags.append('Duplicate of another listing')

    return {
        'score': int(round(max(0.0, min(100.0, score)))),
        'flags': flags,
        'source_trust': trust,
    }
