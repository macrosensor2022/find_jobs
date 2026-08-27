"""Responsibilities and education dimension scoring."""

import re

from config.settings import Config
from services.text_utils import clean_html, find_evidence, word_present

_DEGREE_RANK = {'associates': 1, 'bachelors': 2, 'masters': 3, 'phd': 4}


def score_responsibilities(job_text, coverage=None):
    """Score how much of the job's actual work the candidate can already do.

    Buckets present in the description are detected first, then scored by the
    candidate's coverage strength. A thin description returns a low-confidence
    neutral score rather than a fabricated high one.
    """
    coverage = coverage or Config.RESPONSIBILITY_COVERAGE
    present, covered, uncovered = [], [], []

    for bucket, phrases in Config.RESPONSIBILITY_BUCKETS.items():
        if any(word_present(phrase, job_text) for phrase in phrases):
            present.append(bucket)
            strength = float(coverage.get(bucket, 0.0))
            if strength >= 0.65:
                covered.append(bucket)
            else:
                uncovered.append(bucket)

    if not present:
        return {
            'score': 55.0,
            'present': [], 'covered': [], 'uncovered': [],
            'confidence': 'low',
            'note': 'Description too thin to assess responsibilities',
        }

    total = sum(float(coverage.get(b, 0.0)) for b in present)
    score = total / len(present) * 100.0

    # A job whose duties span many buckets the candidate covers is a better
    # signal than one that mentions a single duty.
    if len(covered) >= 5:
        score = min(100.0, score + 6.0)
    elif len(covered) <= 1 and len(present) >= 3:
        score = max(0.0, score - 5.0)

    confidence = 'high' if len(present) >= 5 else 'medium' if len(present) >= 3 else 'low'
    return {
        'score': round(score, 1),
        'present': present,
        'covered': covered,
        'uncovered': uncovered,
        'confidence': confidence,
        'note': None,
    }


def detect_required_degree(job_text):
    """Highest degree level the posting requires, with the quoted evidence."""
    found = []
    for level, patterns in Config.EDUCATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, job_text, re.I):
                found.append((level, pattern))
                break
    if not found:
        return None, None

    # A posting saying "Bachelor's required, Master's preferred" should be
    # treated as requiring a Bachelor's.
    found.sort(key=lambda item: _DEGREE_RANK.get(item[0], 0))
    for level, pattern in found:
        evidence = find_evidence(job_text, pattern)
        if evidence and re.search(r'\b(require|must|minimum|need)\b', evidence, re.I):
            return level, evidence
    level, pattern = found[0]
    return level, find_evidence(job_text, pattern)


def score_education(description, candidate_level=None):
    candidate_level = candidate_level or Config.CANDIDATE_DEGREE_LEVEL
    job_text = clean_html(description or '')
    if not job_text:
        return {'score': 70.0, 'required': None, 'evidence': None,
                'reasons': [], 'risks': ['No description to check education requirements']}

    required, evidence = detect_required_degree(job_text)
    have = _DEGREE_RANK.get(candidate_level, 3)

    if required is None:
        return {'score': 80.0, 'required': None, 'evidence': None,
                'reasons': ['No specific degree requirement stated'], 'risks': []}

    need = _DEGREE_RANK.get(required, 2)
    if have >= need:
        label = {'associates': "Associate's", 'bachelors': "Bachelor's",
                 'masters': "Master's", 'phd': 'PhD'}[required]
        return {'score': 100.0, 'required': required, 'evidence': evidence,
                'reasons': [f'{label} requirement met by your degree'], 'risks': []}

    return {'score': 35.0, 'required': required, 'evidence': evidence,
            'reasons': [], 'risks': [f'Requires a {required.rstrip("s")} degree']}
