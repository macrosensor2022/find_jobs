"""Work-authorization classification with mandatory evidence.

Rules enforced here:
  * A status is only GREEN or RED when the job text (or an explicit feed field)
    states it. Never inferred from the employer's name or reputation.
  * E-Verify / LCA history are employer facts, surfaced as separate notes. They
    do not change the sponsorship status.
  * When nothing is stated, the status is UNKNOWN, not "probably fine".
"""

from config.settings import Config
from services.text_utils import clean_html, find_evidence

GREEN, YELLOW, RED, UNKNOWN = 'green', 'yellow', 'red', 'unknown'

_STATUS_SCORE = {
    GREEN: 100.0,
    YELLOW: 55.0,
    UNKNOWN: 50.0,
    RED: 0.0,
}

_STATUS_LABEL = {
    GREEN: 'Sponsorship appears possible',
    YELLOW: 'Sponsorship position unclear',
    RED: 'Likely blocked',
    UNKNOWN: 'Unable to determine',
}


def assess_sponsorship(title, description, feed_hint=None, source=None):
    """Classify work-authorization compatibility.

    feed_hint: an explicit machine-readable field from a source feed, e.g.
        SimplifyJobs' sponsorship column. Trusted because it is stated data,
        not an inference.
    """
    text = clean_html(f'{title or ""}. {description or ""}')

    hint = (feed_hint or '').strip().lower().replace(' ', '_') if feed_hint else ''
    if hint in ('no_sponsorship', 'does_not_offer_sponsorship', 'no'):
        return _result(RED, 'Source feed states no sponsorship',
                       f'Feed field: sponsorship = {feed_hint}',
                       source or 'source_feed')
    if hint in ('citizenship_required', 'us_citizenship_required'):
        return _result(RED, 'Source feed states citizenship required',
                       f'Feed field: sponsorship = {feed_hint}',
                       source or 'source_feed')
    if hint in ('offers_sponsorship', 'sponsors', 'yes'):
        return _result(GREEN, 'Source feed states sponsorship offered',
                       f'Feed field: sponsorship = {feed_hint}',
                       source or 'source_feed')

    if not text.strip('. '):
        return _result(UNKNOWN, 'No description available to analyze', None, None)

    for pattern, reason in Config.AUTH_BLOCKING_PATTERNS:
        evidence = find_evidence(text, pattern)
        if evidence:
            return _result(RED, reason, evidence, 'job_description')

    for pattern, reason in Config.AUTH_FRIENDLY_PATTERNS:
        evidence = find_evidence(text, pattern)
        if evidence:
            return _result(GREEN, reason, evidence, 'job_description')

    for pattern, reason in Config.AUTH_UNCLEAR_PATTERNS:
        evidence = find_evidence(text, pattern)
        if evidence:
            return _result(YELLOW, reason, evidence, 'job_description')

    return _result(UNKNOWN, 'Work authorization not mentioned in the posting',
                   None, None)


def _result(status, reason, evidence, evidence_source):
    return {
        'status': status,
        'label': _STATUS_LABEL[status],
        'reason': reason,
        'evidence': evidence,
        'evidence_source': evidence_source,
        'score': _STATUS_SCORE[status],
    }


def employer_notes(is_everify=None, h1b_lca_count=None, match_confidence=None):
    """Employer-level facts, clearly separated from the job's own statement."""
    notes = []
    if is_everify:
        notes.append({
            'fact': 'Employer appears in the USCIS E-Verify participant list',
            'relevance': 'Required for the 24-month STEM OPT extension',
            'confidence': match_confidence,
        })
    if h1b_lca_count:
        notes.append({
            'fact': f'{h1b_lca_count} H-1B LCA filings on record (DOL disclosure data)',
            'relevance': 'Historical sponsorship activity, not a guarantee',
            'confidence': match_confidence,
        })
    return notes
