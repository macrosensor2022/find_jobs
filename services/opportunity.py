"""Opportunity score: how attractive the job is, independent of skill fit."""

from config.settings import Config
from services.freshness import evaluate as evaluate_freshness

_ACCESSIBILITY = {
    'verified': 100.0,
    'unverified': 70.0,
    'unknown': 45.0,
    'search_fallback': 25.0,   # e.g. a Google search link, not a real apply page
    'dead': 0.0,
}

_SPONSORSHIP_CONFIDENCE = {
    'green': 100.0,
    'unknown': 55.0,
    'yellow': 45.0,
    'red': 0.0,
}


def _normalized_weights(overrides=None):
    weights = dict(Config.OPPORTUNITY_WEIGHTS)
    if overrides:
        for key, value in overrides.items():
            if key in weights and value is not None:
                weights[key] = float(value)
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()} if total else weights


def _company_preference(company, watchlist):
    """Watchlist priority only. No assumptions about unlisted companies."""
    if not company:
        return 50.0, None
    name = company.strip().lower()
    for entry in watchlist or []:
        if isinstance(entry, dict):
            target, priority = entry.get('name', ''), entry.get('priority', 2)
        else:
            target, priority = str(entry), 2
        target_l = target.strip().lower()
        if not target_l:
            continue
        if target_l == name or target_l in name or name in target_l:
            return (100.0 if priority == 1 else 85.0), target
    return 50.0, None


def _experience_difficulty(experience):
    """Easier-to-clear requirements are more attractive opportunities."""
    if not experience:
        return 60.0
    if experience.get('hard_drop'):
        return 0.0
    required = experience.get('required_years')
    if experience.get('is_early_career'):
        return 100.0
    if required is None:
        return 75.0
    if required <= 1:
        return 95.0
    if required <= 2:
        return 80.0
    return 50.0


def evaluate_opportunity(job, match_result=None, watchlist=None, weights=None):
    """Return the opportunity score with a per-factor breakdown."""
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    weights = _normalized_weights(weights)
    match_result = match_result or {}

    fresh = evaluate_freshness(get('date_posted'))
    sponsorship_status = (
        (match_result.get('authorization') or {}).get('status')
        or get('sponsorship_status') or 'unknown'
    )
    role = match_result.get('role') or {}
    tier = role.get('tier') or get('role_tier')
    role_priority = {1: 100.0, 2: 85.0, 3: 60.0}.get(tier, 40.0)

    company_score, matched_company = _company_preference(
        get('company'), watchlist if watchlist is not None else Config.WATCHLIST_COMPANIES
    )

    location_score = (match_result.get('location') or {}).get(
        'score', 50.0 if get('worksite_state') is None else 60.0
    )
    accessibility = _ACCESSIBILITY.get(get('application_url_status') or 'unknown', 45.0)
    if not get('application_url'):
        accessibility = min(accessibility, 20.0)

    difficulty = _experience_difficulty(match_result.get('experience'))

    factors = {
        'freshness': fresh['score'],
        'sponsorship': _SPONSORSHIP_CONFIDENCE.get(sponsorship_status, 50.0),
        'role_priority': role_priority,
        'company_preference': company_score,
        'location': location_score,
        'accessibility': accessibility,
        'experience_difficulty': difficulty,
    }

    total = sum(factors[k] * weights[k] for k in factors)

    # Competition signal from DOL metro data, when we actually have it.
    competition = get('competition_score')
    notes = []
    if competition is not None:
        adjustment = (50.0 - float(competition)) * 0.1
        total = max(0.0, min(100.0, total + adjustment))
        notes.append(f'Metro competition adjustment {adjustment:+.1f}')

    salary_min, salary_max = get('salary_min'), get('salary_max')
    if (salary_min or salary_max) and not get('salary_predicted'):
        total = min(100.0, total + 3.0)
        notes.append('Salary disclosed by the employer')

    return {
        'score': int(round(max(0.0, min(100.0, total)))),
        'breakdown': {k: round(v, 1) for k, v in factors.items()},
        'weights': weights,
        'freshness': fresh,
        'watchlist_company': matched_company,
        'notes': notes,
    }
