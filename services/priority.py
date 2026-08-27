"""Application-priority engine.

application_priority_score is NOT a probability of interview. It expresses how
strongly the system recommends spending application time on a job, built from
evidence-backed signals only.

Every sub-score below is derived from stored data or from rules that never
invent facts. When a signal is unknown it scores neutrally and is reported as
unknown on the card.
"""

from config.settings import Config
from services.freshness import evaluate as evaluate_freshness

# Recommendation bands (priority score ceilings).
REC_APPLY_NOW = 80.0
REC_APPLY = 60.0
REC_WATCH = 40.0


def recommendation_for(priority_score):
    """Map an application-priority score (0-100) to an action recommendation."""
    if priority_score is None:
        return {'action': 'WATCH', 'label': 'Watch', 'tone': 'neutral',
                'reason': 'Priority not scored yet'}
    if priority_score >= REC_APPLY_NOW:
        return {'action': 'APPLY NOW', 'label': 'Apply now', 'tone': 'apply',
                'reason': 'Strongest current fit — apply today'}
    if priority_score >= REC_APPLY:
        return {'action': 'APPLY', 'label': 'Apply', 'tone': 'strong',
                'reason': 'Good fit worth applying to this week'}
    if priority_score >= REC_WATCH:
        return {'action': 'WATCH', 'label': 'Watch', 'tone': 'watch',
                'reason': 'Monitor — gaps or unknowns need review first'}
    return {'action': 'SKIP', 'label': 'Skip', 'tone': 'skip',
            'reason': 'Low value for your profile right now'}


# ---------------------------------------------------------------------------
# Phase 5 — Competition signal (never fabricated)
# ---------------------------------------------------------------------------

COMPETITION_LEVELS = ('LOW', 'MODERATE', 'HIGH', 'VERY_HIGH', 'UNKNOWN')


def competition_signal(applicant_count, applicant_count_source, source_feed=None):
    """Classify applicant-count data ONLY when a legitimate source provides it.

    If applicant_count is a real integer this maps it to a band; otherwise the
    signal is UNKNOWN. A feed-supplied density hint is only used when the count
    itself is absent AND the hint is an explicit machine field.
    """
    if isinstance(applicant_count, (int, float)) and applicant_count is not None:
        n = int(applicant_count)
        if n <= 10:
            level = 'LOW'
        elif n <= 25:
            level = 'MODERATE'
        elif n <= 100:
            level = 'HIGH'
        else:
            level = 'VERY_HIGH'
        source = applicant_count_source = (source_feed or 'source')
        return {
            'signal': level,
            'applicant_count': n,
            'applicant_count_source': source_feed,
            'captured_at': None,  # caller stamps a datetime when known
        }
    return {
        'signal': 'UNKNOWN',
        'applicant_count': None,
        'applicant_count_source': None,
        'captured_at': None,
    }


def competition_adjustment(signal):
    """Small opportunity-rank adjustment from a legit competition signal.

    Must never overpower job quality or candidate fit, so the swing is capped.
    """
    mapping = {
        'LOW': +4.0,
        'MODERATE': +2.0,
        'HIGH': -2.0,
        'VERY_HIGH': -4.0,
        'UNKNOWN': 0.0,
    }
    return mapping.get((signal or 'UNKNOWN').upper(), 0.0)


# ---------------------------------------------------------------------------
# Phase 9 — Application readiness
# ---------------------------------------------------------------------------
def application_readiness(job, profile=None, profile_has_resume=None):
    """0-100 readiness with an explicit list of what is missing.

    Checks every item independently; a missing item is reported, never
    fabricated to inflate the score. `profile` is an optional dict carrying a
    resume path; `profile_has_resume` overrides it when the caller already
    knows the answer.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    if profile_has_resume is None:
        profile_has_resume = bool((profile or {}).get('resume_path'))
    checks = []
    score = 100.0

    url = get('application_url')
    url_status = get('application_url_status') or 'unknown'
    if not url:
        score -= 25.0
        checks.append({'ok': False, 'label': 'Application URL captured',
                       'detail': 'No apply URL stored'})
    elif url_status == 'verified':
        checks.append({'ok': True, 'label': 'Application URL verified',
                       'detail': 'Checked live'})
    elif url_status == 'dead':
        score -= 20.0
        checks.append({'ok': False, 'label': 'Application URL verified',
                       'detail': 'URL reported dead'})
    else:
        score -= 12.0
        checks.append({'ok': False, 'label': 'Application URL verified',
                       'detail': f'Status: {url_status or "unverified"}'})

    if get('company'):
        checks.append({'ok': True, 'label': 'Employer identified',
                       'detail': get('company')})
    else:
        score -= 8.0
        checks.append({'ok': False, 'label': 'Employer identified'})

    if get('title'):
        checks.append({'ok': True, 'label': 'Role identified', 'detail': get('title')})
    else:
        score -= 8.0
        checks.append({'ok': False, 'label': 'Role identified'})

    desc = get('description') or ''
    if len(desc) >= Config.MIN_DESCRIPTION_CHARS:
        checks.append({'ok': True, 'label': 'Job description available'})
    else:
        score -= 6.0
        checks.append({'ok': False, 'label': 'Job description available',
                       'detail': 'Description missing or too short'})

    if profile_has_resume or (profile or {}).get('name'):
        checks.append({'ok': True, 'label': 'Resume / profile available'})
    else:
        score -= 6.0
        checks.append({'ok': False, 'label': 'Resume / profile available'})

    auth = get('sponsorship_status') or 'unknown'
    if auth != 'unknown':
        checks.append({'ok': True, 'label': 'Work authorization evaluated',
                       'detail': auth})
    else:
        score -= 5.0
        checks.append({'ok': False, 'label': 'Work authorization evaluated',
                       'detail': 'Unknown'})

    effort = application_effort(get('description'), get('application_url'))
    if effort is not None:
        checks.append({'ok': True, 'label': 'Application requirements detected',
                       'detail': effort})
    else:
        checks.append({'ok': True, 'label': 'Application requirements detected',
                       'detail': 'Banded estimate not computable from thin text'})

    return {
        'score': int(round(max(0.0, min(100.0, score)))),
        'checks': checks,
        'missing': [c['label'] for c in checks if not c['ok']],
    }


# ---------------------------------------------------------------------------
# Phase 10 — Application effort (banded, never precise unless stated)
# ---------------------------------------------------------------------------
_EFFORT_BANDS = {
    '40+': ['resume', 'cover letter', 'portfolio', 'transcript', 'reference',
            'writing sample', 'link to'],
    '20-40': ['assessment', 'questionnaire', 'profile', 'application form'],
    '10-20': ['apply', 'submit'],
}


def application_effort(description, application_url=None):
    """Return a banded effort estimate from visible signals, or None.

    The effort is derived only from what the posting text discloses (form
    fields, attachments, screens). No precise minute value is ever invented.
    """
    if not description:
        return None
    text = (description or '').lower()
    if any(k in text for k in _EFFORT_BANDS['40+']):
        # Cover-letter, portfolio and reference uploads are the strongest signal.
        return '40+ min'
    if any(k in text for k in _EFFORT_BANDS['20-40']):
        return '20-40 min'
    if any(k in text for k in _EFFORT_BANDS['10-20']):
        return '10-20 min'
    return '5-10 min'


# ---------------------------------------------------------------------------
# Phase 2 — Application priority score
# ---------------------------------------------------------------------------
def application_priority(match, opportunity, quality, job, now=None):
    """Evidence-based recommendation score combining candidate fit and the
    practicality of winning + applying. Weights are tuned so candidate fit and
    verification dominate, competition and effort nudge only."""
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)

    match_score = (match or {}).get('score') or 0
    opp_score = (opportunity or {}).get('score') or 0
    quality_score = quality or 0

    # Base on candidate fit, moderated by opportunity and trust in the listing.
    score = (float(match_score) * 0.60
             + float(opp_score) * 0.25
             + float(quality_score) * 0.15)

    # Freshness bonus is contained in opportunity; add a small direct lift for
    # hot postings so the freshest get a nudge without dominating.
    fresh = evaluate_freshness(get('date_posted'))
    if fresh['bucket'] in ('hot', 'fresh'):
        score += 3.0 if fresh['bucket'] == 'hot' else 1.5

    # Entry-level / new-grad signal
    title_l = (get('title') or '').lower()
    if any(x in title_l for x in ('new grad', 'entry level', 'junior',
                                  'associate', 'university grad',
                                  'early career')):
        score += 2.0

    # Competition nudges (never overpowers fit/quality).
    score += competition_adjustment(get('competition_signal'))

    # Strength of the match's own sponsor/auth status already lives in opp.
    return int(round(max(0.0, min(100.0, score))))