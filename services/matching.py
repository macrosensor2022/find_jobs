"""The explainable candidate match engine.

Produces a 0-100 score composed of seven weighted dimensions, plus the
reasons, gaps and risks behind it. Nothing here returns a bare number.
"""

from config.settings import Config
from services.experience import analyze_experience
from services.location_pref import score_location
from services.requirements import score_education, score_responsibilities
from services.role_classifier import classify_role
from services.skills import score_skills
from services.sponsorship import assess_sponsorship
from services.text_utils import clean_html

DIMENSIONS = ('skills', 'responsibilities', 'experience', 'education',
              'role', 'location', 'authorization')

# These dimensions can only be judged from the posting text. When there is no
# usable description they are scored as genuinely unknown (neutral 50) instead
# of taking their optimistic "nothing disqualifying found" default — otherwise a
# job with no description outranks one we can actually verify.
_TEXT_DEPENDENT = ('skills', 'responsibilities', 'experience', 'education',
                   'authorization')
_NEUTRAL = 50.0


def default_weights(overrides=None):
    weights = dict(Config.MATCH_WEIGHTS)
    if overrides:
        for key, value in overrides.items():
            if key in weights and value is not None:
                weights[key] = float(value)
    total = sum(weights.values())
    if total <= 0:
        return dict(Config.MATCH_WEIGHTS)
    return {k: v / total for k, v in weights.items()}


def evaluate_job(job, profile_skills=None, weights=None, location_prefs=None):
    """Score one job against the candidate profile.

    `job` is a plain dict (or model-like object) with title/company/location/
    description and optional worksite_state, is_remote, sponsorship_hint.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)

    title = get('title') or ''
    description = get('description') or ''
    company = get('company') or ''
    location = get('location') or ''
    clean_desc = clean_html(description)
    # Company name is deliberately excluded from skill matching: a company
    # called "Spark Analytics" must not inflate the technical score.
    job_text = f'{title}\n{clean_desc}'.lower()

    weights = default_weights(weights)
    skills_profile = profile_skills or Config.PROFILE_SKILLS

    role = classify_role(title, clean_desc)
    exp = analyze_experience(title, clean_desc)
    skills = score_skills(job_text, skills_profile)
    resp = score_responsibilities(job_text)
    edu = score_education(clean_desc)
    loc = score_location(location, clean_desc,
                         state=get('worksite_state'),
                         is_remote=get('is_remote'),
                         preferences=location_prefs)
    auth = assess_sponsorship(title, clean_desc,
                              feed_hint=get('sponsorship_hint'),
                              source=get('source'))

    dimension_scores = {
        'skills': skills['score'],
        'responsibilities': resp['score'],
        'experience': exp['score'],
        'education': edu['score'],
        'role': role['score'],
        'location': loc['score'],
        'authorization': auth['score'],
    }

    has_text = len(clean_desc.strip()) >= Config.MIN_DESCRIPTION_CHARS
    if not has_text:
        for dimension in _TEXT_DEPENDENT:
            # Only pull optimistic scores down; a genuine red flag found in the
            # title (e.g. "Senior") must keep its penalty.
            dimension_scores[dimension] = min(dimension_scores[dimension], _NEUTRAL)

    total = sum(dimension_scores[d] * weights[d] for d in DIMENSIONS)
    score = int(round(max(0.0, min(100.0, total))))

    reasons, gaps, risks = _explain(skills, resp, exp, edu, role, loc, auth)
    if not has_text:
        risks.insert(0, 'Provisional score: the posting text was not available, '
                        'so requirements could not be checked')

    eligible = not exp['hard_drop'] and not role['avoid'] and auth['status'] != 'red'
    disqualifiers = []
    if exp['hard_drop']:
        disqualifiers.extend(exp['reasons'])
    if role['avoid']:
        disqualifiers.extend(role['reasons'])
    if auth['status'] == 'red':
        disqualifiers.append(auth['reason'])

    return {
        'score': score,
        'eligible': eligible,
        'disqualifiers': disqualifiers,
        'weights': weights,
        'breakdown': {d: round(dimension_scores[d], 1) for d in DIMENSIONS},
        'contributions': {
            d: round(dimension_scores[d] * weights[d], 2) for d in DIMENSIONS
        },
        'reasons': reasons,
        'gaps': gaps,
        'risks': risks,
        'role': role,
        'experience': exp,
        'skills': skills,
        'responsibilities': resp,
        'education': edu,
        'location': loc,
        'authorization': auth,
        'company': company,
        'confidence': _confidence(skills, resp, clean_desc),
    }


def _explain(skills, resp, exp, edu, role, loc, auth):
    reasons, gaps, risks = [], [], []

    for skill in skills['matched'][:8]:
        reasons.append(skill)
    for skill in skills['missing'][:6]:
        gaps.append(skill)
    if skills['note']:
        risks.append(skills['note'])

    for bucket in resp['covered'][:4]:
        reasons.append(bucket.replace('_', ' ').title())
    for bucket in resp['uncovered'][:3]:
        gaps.append(bucket.replace('_', ' ').title() + ' experience is limited')
    if resp['note']:
        risks.append(resp['note'])

    reasons.extend(exp['reasons'] if not exp['hard_drop'] else [])
    risks.extend(exp['risks'])
    if exp['hard_drop']:
        risks.extend(exp['reasons'])
    if exp['required_years'] is not None and exp['required_years'] >= 2:
        gaps.append(f"{exp['required_years']:g} years experience required")

    reasons.extend(edu['reasons'])
    risks.extend(edu['risks'])
    reasons.extend(role['reasons'] if role['tier'] else [])
    if not role['tier'] and not role['avoid']:
        risks.extend(role['reasons'])
    if role['avoid']:
        risks.extend(role['reasons'])
    reasons.extend(loc['reasons'])
    risks.extend(loc['risks'])

    if auth['status'] == 'green':
        reasons.append(auth['reason'])
    elif auth['status'] == 'red':
        risks.append(auth['reason'])
    elif auth['status'] == 'yellow':
        risks.append(auth['reason'])

    dedupe = lambda seq: list(dict.fromkeys(x for x in seq if x))
    return dedupe(reasons), dedupe(gaps), dedupe(risks)


def _confidence(skills, resp, description):
    """How much the score can be trusted, given description completeness."""
    if len(description) < 200:
        return 'low'
    if skills['confidence'] == 'high' and resp['confidence'] in ('high', 'medium'):
        return 'high'
    if skills['confidence'] == 'low' and resp['confidence'] == 'low':
        return 'low'
    return 'medium'
