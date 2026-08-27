"""Role-family and hidden-fit classification (Phase 6 & 7).

Expands the existing role classification into a first-class family taxonomy
and detects "hidden fits": titles that are not obviously data-engineering but
whose responsibilities + technologies align strongly with Vinay's target
profile (SQL, Python, Azure, ETL, Power BI).

Signals are taken from the job's own text — never inferred from the employer.
QA-only automation is deliberately not given a high score.
"""

import re

from services.text_utils import clean_html, word_present


def clean_text(text):
    return clean_html(text or '')

FAMILY_LABELS = {
    'DATA_ENGINEERING': 'Data Engineering',
    'ANALYTICS_BI': 'Analytics / BI',
    'CLOUD_DATA': 'Cloud Data',
    'DATA_AUTOMATION': 'Data Automation',
    'AI_DATA': 'AI / Data',
    'DATABASE_SQL': 'Database / SQL',
    'DATA_QUALITY': 'Data Quality',
    'OTHER': 'Other',
}

# Family -> title / role keywords (first strong signal).
_FAMILY_TITLES = {
    'DATA_ENGINEERING': [
        'data engineer', 'data engineering', 'analytics engineer',
        'data pipeline', 'data platform engineer', 'data warehouse engineer',
        'data integration engineer', 'data ops', 'etl developer',
        'data infrastructure', 'backend data',
    ],
    'ANALYTICS_BI': [
        'analyst', 'business intelligence', 'bi analyst', 'bi engineer',
        'reporting analyst', 'analytics', 'power bi', 'data analyst',
        'insight',
    ],
    'CLOUD_DATA': [
        'cloud data', 'azure data', 'azure data engineer', 'cloud engineer',
        'data cloud',
    ],
    'DATA_AUTOMATION': [
        'data automation', 'workflow automation', 'process automation',
        'etl automation', 'automation engineer', 'azure automation',
        'power automate', 'data integration specialist',
    ],
    'AI_DATA': [
        'data scientist', 'ml engineer', 'machine learning', 'ai engineer',
        'nlp', 'applied scientist', 'research engineer', 'decision scientist',
    ],
    'DATABASE_SQL': [
        'sql developer', 'database developer', 'sql programmer',
        'database engineer', 'sql data analyst', 'tsql', 'mssql',
    ],
    'DATA_QUALITY': [
        'data quality', 'quality analyst', 'data governance',
    ],
}

# Technology / responsibility signals that reveal a DATA_AUTOMATION role even
# when the title is generic ("Technology Analyst", "Automation Engineer").
_DATA_AUTOMATION_SIGNALS = [
    # Data / cloud orchestration and integration signals — the signals that
    # make an "automation" role a real data-automation lane. Generic QA
    # automation does NOT include these, so it is correctly excluded.
    'python', 'sql', 'api', 'etl', 'data pipeline', 'data pipelines',
    'azure function', 'azure functions', 'power automate', 'workflow orchestration',
    'orchestration', 'data integration', 'azure automation',
]
_QA_ONLY_SIGNALS = [
    'qa', 'quality assurance', 'test automation', 'selenium', 'test case',
    'test cases', 'manual test', 'regression test', 'regression testing',
    'unit test', 'functional test', 'test plan', 'test runner',
    'automated testing', 'test framework',
]

# Hidden-fit: a non-data title whose responsibilities/techs line up with the
# candidate's strengths (SQL, Python, Azure, ETL, Power BI).
_HIDDEN_FIT_TECH = [
    'sql', 'python', 'azure', 'etl', 'power bi', 'data warehouse',
    'ssis', 'reporting', 'dashboard', 'data mart', 'data modeling',
]

# Titles that are *obviously* data/analysis roles on their own (no hidden fit
# needed). 'analyst' alone is deliberately excluded (financial/ops analysts
# are not data roles on face value).
_OBVIOUS_DATA_TITLE = [
    'data engineer', 'data engineering', 'analytics engineer',
    'data analyst', 'business intelligence', 'bi analyst', 'bi engineer',
    'etl developer', 'sql developer', 'data scientist', 'ml engineer',
    'machine learning engineer', 'ai engineer', 'data automation',
    'azure data engineer', 'cloud data engineer', 'data warehouse engineer',
    'data platform engineer', 'data quality', 'data governance',
    'data integration engineer', 'data pipeline',
]


def classify_family(title='', description=''):
    """Return a family dict: family, label, matched_phrase, hidden_fit, reasons."""
    text = f'{title or ""}. {clean_text(description or "")}'.lower()
    title_l = (title or '').lower()

    # 1) Explicit family via title phrases (first match wins).
    family = None
    matched = None
    for fam, phrases in _FAMILY_TITLES.items():
        for phrase in phrases:
            if phrase in title_l:
                family, matched = fam, phrase
                break
        if family:
            break

    # 2) Fall back to responsibilities/techs when the title is ambiguous
    #    (e.g. generic "Technology Analyst", "Automation Engineer").
    keyword_fallbacks = {
        'DATA_ENGINEERING': ['etl', 'data pipeline', 'data warehouse', 'etl pipeline'],
        'ANALYTICS_BI': ['dashboard', 'reporting', 'business intelligence',
                         'power bi', 'analytics'],
        'CLOUD_DATA': ['azure data', 'aws data', 'cloud data'],
        'DATA_AUTOMATION': ['azure function', 'power automate', 'workflow orchestration',
                            'data integration', 'etl automation'],
        'DATABASE_SQL': ['sql server', 'database'],
        'DATA_QUALITY': ['data quality', 'data governance'],
        'AI_DATA': ['machine learning', 'data science', 'model'],
    }

    if not family:
        for fam, kws in keyword_fallbacks.items():
            if any(k in text for k in kws):
                family, matched = fam, kws[0]
                break

    # 3) DATA_AUTOMATION refinement — separate real data automation from
    #    QA-only automation.
    if family == 'DATA_AUTOMATION':
        has_data_signal = any(s in text for s in _DATA_AUTOMATION_SIGNALS)
        qa_signal = any(q in text for q in _QA_ONLY_SIGNALS)
        if qa_signal and not has_data_signal:
            family, matched = 'OTHER', 'qa-only automation'

    if not family:
        family, matched = 'OTHER', None

    # 4) Hidden fit — a non-obvious title whose responsibilities/techs align
    #    strongly with the candidate's target stack. Runs regardless of family
    #    so generic titles (Technology Analyst, Automation Engineer) that the
    #    fallback placed in ANALYTICS_BI/OTHER still surface as hidden fits.
    obvious_title = any(p in title_l for p in _OBVIOUS_DATA_TITLE)
    hits = [t for t in _HIDDEN_FIT_TECH if t in text]
    hidden = (not obvious_title) and len(hits) >= 2
    hidden_reason = (
        'Title is not Data Engineer, but responsibilities strongly align with '
        'your target profile (SQL, Python, Azure, ETL, Power BI).'
        if hidden else None
    )

    reasons = [matched] if matched else []
    if family == 'OTHER' and not matched:
        reasons.append('Role family not confidently classifiable from title')

    return {
        'family': family,
        'label': FAMILY_LABELS.get(family, family),
        'matched_phrase': matched,
        'hidden_fit': hidden,
        'hidden_fit_reason': hidden_reason,
        'reasons': reasons,
    }


def is_data_automation(family, description='', title_text=''):
    """First-class DATA_AUTOMATION lane: data-flavoured automation only.

    QA-only automation returns False.
    """
    text = f'{title_text or ""} {clean_text(description or "")}'.lower()
    has_signal = any(s in text for s in _DATA_AUTOMATION_SIGNALS)
    qa_signal = any(q in text for q in _QA_ONLY_SIGNALS)
    if family != 'DATA_AUTOMATION':
        return False
    if qa_signal and not has_signal:
        return False
    return True