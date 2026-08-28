"""Golden Opportunity Score (V3 Part 21).

A single composite "how valuable is it to spend time on this right now" score,
DERIVED from the existing ranking sub-scores and NEVER replacing them. It is a
sibling to final_score / application_priority_score.

Weighting principles (per spec):
  JOB FIT          — highest
  FRESHNESS        — high
  AUTHORIZATION    — high
  JOB QUALITY      — high
  APPLICATION EFFORT — moderate
  INDUSTRY OPPORTUNITY — moderate
  CONTACT AVAILABILITY — moderate
  COMPETITION      — moderate when evidence exists

Contact availability is a MODEST component and can never dominate: a great job
with no contact still scores well.
"""

from config.settings import Config


def effort_score(effort_estimate):
    """Map effort to a 0-100 score (lower effort -> higher)."""
    mapping = {
        '5-10 min': 100.0,
        '10-20 min': 85.0,
        '20-40 min': 60.0,
        '40+ min': 35.0,
    }
    if isinstance(effort_estimate, str):
        return mapping.get(effort_estimate, 70.0)
    return 70.0


def golden_opportunity_score(match_score, freshness_score, auth_status,
                            quality_score, effort_estimate=None,
                            industry_opp_score=None, contact_relevance_score=None,
                            competition_signal=None):
    """Compute the golden score from already-evaluated signals.

    All inputs are 0-100 (or None -> neutral). Returns a dict with the blended
    score and the weight breakdown so the deck is explainable.
    """
    w = Config.GOLDEN_SCORE_WEIGHTS
    total = sum(w.values()) or 1.0

    # Authori compatibility: green/unknown(green-leaning) high; red low.
    auth_score = {
        'green': 100.0, 'unknown': 55.0, 'yellow': 40.0, 'red': 5.0,
    }.get((auth_status or 'unknown'), 50.0)

    industry = industry_opp_score if industry_opp_score is not None else 50.0
    contact = contact_relevance_score if contact_relevance_score is not None else 30.0
    comp = {
        'LOW': 100.0, 'MODERATE': 70.0, 'HIGH': 40.0, 'VERY_HIGH': 20.0, 'UNKNOWN': 0.0,
    }.get((competition_signal or 'UNKNOWN'), 0.0)

    raw = (
        (match_score or 0) * w['job_fit']
        + (freshness_score or 0) * w['freshness']
        + auth_score * w['authorization']
        + (quality_score or 0) * w['job_quality']
        + effort_score(effort_estimate) * w['application_effort']
        + float(industry) * w['industry_opportunity']
        + float(contact) * w['contact_relevance']
        + float(comp) * w['competition']
    ) / total
    score = round(max(0.0, min(100.0, raw)), 2)

    return {
        'score': score,
        'breakdown': {
            'match': match_score or 0,
            'freshness': freshness_score or 0,
            'authorization': round(auth_score, 1),
            'quality': quality_score or 0,
            'effort': effort_score(effort_estimate),
            'industry_opportunity': round(industry, 1),
            'contact_relevance': round(contact, 1),
            'competition': round(comp, 1),
        },
        'weights': {k: round(v / total, 3) for k, v in w.items()},
        'note': 'Composite signal derived from existing match/priority scores. '
                'A job without a contact can still be a strong opportunity.',
    }


def _comp_map(value):
    return {'LOW': 100.0, 'MODERATE': 70.0, 'HIGH': 40.0, 'VERY_HIGH': 10.0,
            'UNKNOWN': 0.0}.get(value or 'UNKNOWN', 0.0)