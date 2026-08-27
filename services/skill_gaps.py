"""Skill-gap matrix (Phase 8).

For each job, classify every requested skill as MATCHED / PARTIAL / MISSING.
A partial match means the profile carries a closely related skill accepted as
a bridge (e.g. profile has SQL, posting asks T-SQL). Must-have vs nice-to-have
mirrors the business line in the posting (required vs preferred/preferred).

No job is rejected for a nice-to-have gap.
"""

import re

from config.settings import Config
from services.skills import SKILL_VOCABULARY, extract_job_skills, _profile_lookup
from services.text_utils import clean_html, word_present

# canonical skill -> a list of closely related profile skills that count as a
# partial (bridgeable) match.
_PARTIAL_BRIDGES = {
    'T-SQL': ['SQL', 'SQL Server'],
    'PL/SQL': ['SQL'],
    'Azure Data Factory': ['Azure', 'ETL'],
    'Azure Synapse': ['Azure', 'AWS'],
    'Snowflake': ['SQL', 'Azure'],
    'Redshift': ['SQL', 'AWS'],
    'BigQuery': ['SQL', 'GCP'],
    'Databricks': ['Spark', 'Azure'],
    'Spark': ['Python'],
    'dbt': ['SQL', 'ETL'],
    'Kafka': ['Python'],
    'Airflow': ['S', 'etl', 'python'],
    'Power BI': ['Tableau'],
    'Tableau': ['Power BI'],
    'Looker': ['Power BI'],
    'TensorFlow': ['PyTorch'],
    'PyTorch': ['TensorFlow'],
    'MLOps': ['Docker', 'Kubernetes'],
    'Data Modeling': ['SQL'],
    'Data Warehousing': ['SQL', 'ETL'],
}

# Hard requirements vs nice-to-haves: when a posting phrases the skill with one
# of these cues it is a must-have; preferred/plus/bonus cues make it a
# nice-to-have.
_REQUIRED_CUE = re.compile(
    r'\b(require[sd]?|must have|must|minimum|at least|essential|mandatory|'
    r'strong(?:ly)? (?:required|preferred)|need[ed]?)\b', re.I,
)
_NICE_CUE = re.compile(
    r'\b(prefer(?:red)?|nice to have|plus|bonus|desirable|ideal(?:ly)?|'
    r'a plus|advantageous|good to have)\b', re.I,
)


def _find_sentence_containing(text, alias):
    """Return the sentence that mentions an alias, for cue detection."""
    for sentence in re.split(r'(?<=[.!?])\s+', text or ''):
        if word_present(alias, sentence):
            return sentence
    return None


def _bridge_aliases(skill):
    return _PARTIAL_BRIDGES.get(skill, [])


def skill_gap_matrix(job):
    """Return MATCHED/PARTIAL/MISSING matrix plus must/nice separation.

    Works whether `job` is a dict or a model with a .description attribute.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    description = clean_html(get('description') or '')
    title = get('title') or ''
    job_text = f'{title}. {description}'.lower()
    if len(description.strip()) < Config.MIN_DESCRIPTION_CHARS:
        return {
            'matrix': [], 'matched': [], 'partial': [], 'missing': [],
            'must_have_gaps': [], 'nice_to_have_gaps': [],
            'note': 'Description too thin to build a reliable skill matrix',
        }

    profile = _profile_lookup(get('profile_skills') or [])
    required = extract_job_skills(job_text)

    matrix = []
    matched, partial, missing = [], [], []
    must_have_gaps, nice_to_have_gaps = [], []

    for skill in required:
        canonical = skill
        if profile.get(canonical.lower()):
            state = 'MATCHED'; pct = 100
            matched.append(canonical)
            sentence = None
        else:
            # Try a partial bridge.
            bridged = False
            for bridge in _bridge_aliases(canonical):
                if profile.get(bridge.lower()):
                    bridged = True
                    break
            if bridged:
                state = 'PARTIAL'; pct = 70
                partial.append(canonical)
            else:
                state = 'MISSING'; pct = 0
                missing.append(canonical)

        # Determine required vs nice-to-have from posting phrasing.
        aliases = SKILL_VOCABULARY.get(skill, [skill])
        sentence = None
        for alias in aliases:
            sentence = _find_sentence_containing(job_text, alias)
            if sentence:
                break
        is_required = True
        if sentence and _NICE_CUE.search(sentence) and not _REQUIRED_CUE.search(sentence):
            is_required = False
        if state == 'MISSING':
            if is_required:
                must_have_gaps.append(canonical)
            else:
                nice_to_have_gaps.append(canonical)

        matrix.append({
            'skill': canonical, 'status': state,
            'pct': pct, 'required': is_required,
        })

    matrix.sort(key=lambda m: (0 if m['status'] == 'MATCHED' else
                               1 if m['status'] == 'PARTIAL' else 2,
                               -m['pct']))
    return {
        'matrix': matrix,
        'matched': matched, 'partial': partial, 'missing': missing,
        'must_have_gaps': must_have_gaps,
        'nice_to_have_gaps': nice_to_have_gaps,
        'note': None,
    }