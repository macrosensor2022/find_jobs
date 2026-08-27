"""Semantic-ish role classification into target tiers.

A job is not rejected for failing an exact title match. Titles are compared
against tier phrases by exact containment first, then by token overlap, so
"Data Platform Analyst II" still lands in a tier.
"""

import re

from config.settings import Config
from services.text_utils import tokens, word_present

_SENIOR_RE = re.compile(
    r'\b(senior|sr\.?|staff|principal|lead|architect|manager|director|head of|'
    r'vp|vice president|chief|distinguished|fellow)\b', re.I,
)
_MID_RE = re.compile(r'\b(ii|iii|iv|2|3|mid[\s\-]?level)\b', re.I)
_ENTRY_RE = re.compile(
    r'\b(new grad(?:uate)?|university grad(?:uate)?|entry[\s\-]?level|junior|jr\.?|'
    r'associate|early career|graduate program|campus|rotational|apprentice|'
    r'trainee|emerging talent|i)\b', re.I,
)
_INTERN_RE = re.compile(r'\b(intern(?:ship)?|co[\s\-]?op|coop)\b', re.I)

# Generic words that carry no discriminating power in token overlap.
_STOPWORDS = {
    'the', 'a', 'an', 'of', 'and', 'or', 'for', 'to', 'in', 'at', 'with',
    'i', 'ii', 'iii', 'iv', 'new', 'grad', 'graduate', 'junior', 'jr',
    'senior', 'sr', 'staff', 'principal', 'lead', 'entry', 'level',
    'associate', 'intern', 'internship', 'co', 'op', 'remote', 'hybrid',
    'us', 'usa', 'full', 'time', 'fulltime', 'campus', 'university', '2026',
    '2027', 'early', 'career',
    # Too generic alone — "Growth Engineer" must not match "Analytics Engineer"
    'engineer', 'developer', 'analyst', 'specialist', 'coordinator',
}

# Overlap matches must share at least one of these anchors (or full phrase).
_ROLE_ANCHORS = {
    'data', 'analytics', 'analytic', 'bi', 'etl', 'elt', 'sql', 'warehouse',
    'pipeline', 'pipelines', 'ml', 'machine', 'learning', 'intelligence',
    'quality', 'governance', 'integration', 'scientist', 'nlp', 'spark',
    'databricks', 'snowflake', 'dbt', 'airflow', 'ssis', 'azure',
}


def detect_seniority(title):
    """Return entry | mid | senior | intern | unknown."""
    t = title or ''
    if _INTERN_RE.search(t):
        return 'intern'
    if _SENIOR_RE.search(t):
        return 'senior'
    if _ENTRY_RE.search(t):
        return 'entry'
    if _MID_RE.search(t):
        return 'mid'
    return 'unknown'


def _significant(phrase):
    return {t for t in tokens(phrase) if t not in _STOPWORDS and len(t) > 1}


def _best_overlap(title):
    """Best (tier, phrase, overlap_ratio) across all tier phrases."""
    title_tokens = _significant(title)
    if not title_tokens:
        return None, None, 0.0
    # Pure SWE/backend/growth titles without a data anchor never overlap-match
    if not (title_tokens & _ROLE_ANCHORS):
        return None, None, 0.0
    best = (None, None, 0.0)
    for tier, phrases in Config.ROLE_TIERS.items():
        for phrase in phrases:
            phrase_tokens = _significant(phrase)
            if not phrase_tokens:
                continue
            shared = phrase_tokens & title_tokens
            if not shared:
                continue
            # Require a discriminating token — not just "engineer"/"analyst"
            if not (shared & _ROLE_ANCHORS) and len(shared) < 2:
                continue
            coverage = len(shared) / len(phrase_tokens)
            precision = len(shared) / len(title_tokens)
            ratio = (2 * coverage * precision) / (coverage + precision)
            if ratio > best[2]:
                best = (tier, phrase, ratio)
    return best


def classify_role(title, description=''):
    """Classify a job title into a target tier with an explainable score."""
    title = (title or '').strip()
    result = {
        'family': None,
        'tier': None,
        'score': Config.ROLE_UNKNOWN_SCORE,
        'seniority': detect_seniority(title),
        'matched_phrase': None,
        'avoid': False,
        'method': 'unknown',
        'reasons': [],
    }
    if not title:
        return result

    title_l = title.lower()

    for avoid_term in Config.ROLE_AVOID:
        if word_present(avoid_term.strip(), title_l):
            result.update({
                'avoid': True,
                'score': 5.0,
                'method': 'avoid_list',
                'family': 'off_target',
                'reasons': [f'Title matches off-target role: "{avoid_term.strip()}"'],
            })
            return result

    # Exact phrase containment wins (most reliable signal).
    for tier in sorted(Config.ROLE_TIERS):
        for phrase in Config.ROLE_TIERS[tier]:
            if phrase in title_l:
                result.update({
                    'family': phrase,
                    'tier': tier,
                    'score': Config.ROLE_TIER_WEIGHT[tier],
                    'matched_phrase': phrase,
                    'method': 'exact_phrase',
                    'reasons': [f'Tier {tier} role: "{phrase}"'],
                })
                return _apply_seniority(result)

    tier, phrase, ratio = _best_overlap(title_l)
    if tier and ratio >= 0.6:
        base = Config.ROLE_TIER_WEIGHT[tier]
        result.update({
            'family': phrase,
            'tier': tier,
            'score': round(base * (0.65 + 0.35 * ratio), 1),
            'matched_phrase': phrase,
            'method': 'token_overlap',
            'reasons': [
                f'Similar to tier {tier} role "{phrase}" ({int(ratio * 100)}% title overlap)'
            ],
        })
        return _apply_seniority(result)

    # Last resort: data-adjacent titles get partial credit rather than a
    # hard rejection, and we say plainly that we could not classify it.
    adjacent = ['data', 'analytics', 'analyst', 'reporting', 'warehouse',
                'business intelligence', 'etl', 'database', 'insight']
    if any(word_present(term, title_l) for term in adjacent):
        result.update({
            'score': max(Config.ROLE_UNKNOWN_SCORE, 55.0),
            'method': 'adjacent_keyword',
            'family': 'data_adjacent',
            'reasons': ['Data-adjacent title, exact role family unclear'],
        })
    else:
        result['reasons'] = ['Role family could not be determined from the title']
    return _apply_seniority(result)


def _apply_seniority(result):
    """Seniority modifies role alignment, it does not redefine the family."""
    seniority = result['seniority']
    if seniority == 'senior':
        result['score'] = round(result['score'] * 0.25, 1)
        result['reasons'].append('Senior/lead-level title')
    elif seniority == 'mid':
        result['score'] = round(result['score'] * 0.8, 1)
        result['reasons'].append('Mid-level title (II/III)')
    elif seniority == 'entry':
        result['score'] = round(min(100.0, result['score'] * 1.1), 1)
        result['reasons'].append('Early-career title')
    return result
