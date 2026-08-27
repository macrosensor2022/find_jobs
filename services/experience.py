"""Structured experience-requirement analysis.

The goal is to reject jobs the candidate genuinely cannot get (a Staff role
asking for 8+ years) without rejecting a good role because one sentence
happens to mention "5 years of industry trends".
"""

import re

from config.settings import Config
from services.role_classifier import detect_seniority
from services.text_utils import clean_html, find_evidence, sentences

_NUM_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}

# "3+ years", "3-5 years", "minimum of 4 years", "four years of experience"
_YEARS_RE = re.compile(
    r'(?:(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)\s*(\d{1,2})|(\d{1,2})\s*(?:\+|plus)?|'
    r'(one|two|three|four|five|six|seven|eight|nine|ten))\s*'
    r'(?:\+\s*)?(?:years?|yrs?)\b',
    re.I,
)
_PREFERRED_CUE = re.compile(
    r'\b(prefer|preferred|preferably|nice to have|plus|bonus|desirable|ideally|'
    r'a plus|advantageous)\b', re.I,
)
_REQUIRED_CUE = re.compile(
    r'\b(require[sd]?|must have|minimum|at least|need|mandatory|essential)\b', re.I,
)
# Sentences where a year count is not an experience requirement.
_NOT_A_REQUIREMENT = re.compile(
    r'\b(founded|since \d{4}|over \d+ years (?:of )?(?:innovation|history|serving|'
    r'excellence|growth)|\d+ years? ago|past \d+ years|last \d+ years|'
    r'in business|anniversary)\b', re.I,
)
_EARLY_CAREER_RE = re.compile(
    r'\b(new grad(?:uate)?s?|university grad(?:uate)?|recent grad(?:uate)?s?|'
    r'entry[\s\-]?level|early career|no (?:prior )?experience (?:is )?(?:required|necessary)|'
    r'0[\s\-]*(?:to|-)?\s*2 years|graduating (?:in )?20\d\d|campus hire|'
    r'rotational program|graduate program|emerging talent)\b', re.I,
)
_INTERN_RE = re.compile(r'\b(intern(?:ship)?|co[\s\-]?op|coop)\b', re.I)


def _extract_year_mentions(text):
    """Yield (years, is_preferred, sentence) for genuine experience mentions."""
    out = []
    for sentence in sentences(text):
        if _NOT_A_REQUIREMENT.search(sentence):
            continue
        if not re.search(r'\b(experience|exp\b|background|working)\b', sentence, re.I):
            # A bare year count with no experience context is unreliable.
            if not re.search(r'\d{1,2}\s*\+?\s*(?:years?|yrs?)\b', sentence, re.I):
                continue
            if not re.search(r'\b(years?|yrs?)\s+(?:in|with|of)\b', sentence, re.I):
                continue
        for match in _YEARS_RE.finditer(sentence):
            low, high, single, word = match.groups()
            if low:
                years = float(low)
            elif single:
                years = float(single)
            elif word:
                years = float(_NUM_WORDS[word.lower()])
            else:
                continue
            preferred = bool(_PREFERRED_CUE.search(sentence)) and not _REQUIRED_CUE.search(sentence)
            out.append((years, preferred, sentence))
    return out


def analyze_experience(title, description):
    """Return a structured, explainable experience assessment."""
    title = title or ''
    desc = clean_html(description or '')
    combined = f'{title}. {desc}'

    seniority = detect_seniority(title)
    mentions = _extract_year_mentions(combined)

    required = [m for m in mentions if not m[1]]
    preferred = [m for m in mentions if m[1]]

    required_years = min((m[0] for m in required), default=None)
    preferred_years = min((m[0] for m in preferred), default=None)
    max_required = max((m[0] for m in required), default=None)

    evidence = []
    hard_drop = False
    reasons = []
    risks = []

    if required:
        pick = min(required, key=lambda m: m[0])
        evidence.append(pick[2])
    elif preferred:
        pick = min(preferred, key=lambda m: m[0])
        evidence.append(pick[2])

    is_intern = bool(_INTERN_RE.search(title))
    is_early = bool(_EARLY_CAREER_RE.search(combined))

    if getattr(Config, 'SEEKING_FULL_TIME_NEW_GRAD', True) and is_intern:
        hard_drop = True
        reasons.append('Internship/co-op role, but you are targeting full-time')

    if seniority == 'senior':
        hard_drop = True
        reasons.append('Senior/staff/principal/lead title')
        senior_evidence = find_evidence(
            title, r'senior|sr\.?|staff|principal|lead|architect|manager|director'
        )
        if senior_evidence:
            evidence.append(senior_evidence)

    drop_threshold = float(Config.EXP_HARD_DROP_YEARS)
    if required_years is not None and required_years >= 5:
        hard_drop = True
        reasons.append(f'Requires {required_years:g}+ years of experience')
    elif required_years is not None and required_years >= drop_threshold:
        if is_early:
            # Contradictory posting: keep it but flag the risk.
            risks.append(
                f'Description mentions {required_years:g}+ years despite '
                f'early-career language'
            )
        else:
            hard_drop = True
            reasons.append(f'Requires {required_years:g}+ years of experience')

    score = _score(required_years, preferred_years, seniority, is_early, hard_drop)

    if is_early and not hard_drop:
        reasons.append('Explicitly open to new grads / early career')
    if required_years is None and preferred_years is None and not hard_drop:
        reasons.append('No explicit years-of-experience requirement found')
    if preferred_years is not None and preferred_years >= drop_threshold:
        risks.append(f'{preferred_years:g}+ years preferred (not required)')
    if max_required is not None and required_years is not None and max_required > required_years:
        risks.append(f'Range up to {max_required:g} years mentioned')

    return {
        'required_years': required_years,
        'preferred_years': preferred_years,
        'seniority': seniority,
        'is_early_career': is_early,
        'is_internship': is_intern,
        'hard_drop': hard_drop,
        'score': score,
        'evidence': evidence[:2],
        'reasons': reasons,
        'risks': risks,
    }


def _score(required_years, preferred_years, seniority, is_early, hard_drop):
    if hard_drop:
        return 0.0
    if required_years is None:
        base = 90.0 if is_early else 72.0
    elif required_years <= 1:
        base = 100.0
    elif required_years <= 2:
        base = 88.0
    elif required_years < 3:
        base = 76.0
    elif required_years < 4:
        base = 55.0
    else:
        base = 30.0

    if preferred_years is not None and preferred_years >= 3:
        base -= 8.0
    if seniority == 'mid':
        base -= 10.0
    if seniority == 'entry':
        base = min(100.0, base + 6.0)
    return round(max(0.0, min(100.0, base)), 1)
