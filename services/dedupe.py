"""Cross-source deduplication.

The same posting reaches us from an employer ATS, an aggregator and a feed with
different IDs and URLs. We collapse them to one job and prefer the official
employer posting, keeping the other source URLs for reference.
"""

import re
from urllib.parse import urlsplit

# Higher wins when choosing which duplicate to keep.
SOURCE_PRIORITY = {
    'greenhouse': 100, 'lever': 100, 'ashby': 100, 'smartrecruiters': 100,
    'ats': 95, 'workday': 90,
    'github_newgrad': 80, 'github_intern': 78,
    'themuse': 60, 'remotive': 55, 'remoteok': 55, 'arbeitnow': 50,
    'adzuna': 40, 'jsearch': 35,
    'linkedin': 30, 'nuworks': 25,
}

_COMPANY_SUFFIXES = re.compile(
    r'\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|'
    r'plc|gmbh|holdings|group|technologies|technology|labs|solutions|services|'
    r'systems|software|global|usa|us)\b', re.I,
)
_LEVEL_TOKENS = re.compile(
    r'\b(i{1,3}|iv|v|1|2|3|senior|sr|junior|jr|associate|entry[\s\-]?level|'
    r'new grad(?:uate)?|university grad(?:uate)?|early career|full[\s\-]?time|'
    r'remote|hybrid|onsite|us|usa|2026|2027|intern|internship|co[\s\-]?op)\b',
    re.I,
)


def normalize_company(company):
    text = (company or '').lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = _COMPANY_SUFFIXES.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalize_title(title):
    """Normalize a title for identity comparison.

    Bracketed text is kept, not discarded: employers use it to distinguish real
    postings ("... (Visual Search)" vs "... (Basic Ranking)") and dropping it
    collapses genuinely different jobs into one.
    """
    text = (title or '').lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = _LEVEL_TOKENS.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalize_url(url):
    """Strip tracking params and trailing slashes so URLs compare equal.

    Query strings are dropped entirely (they carry per-scrape tracking ids), but
    identifiers that live in the path are preserved, so two different postings
    on the same board never collapse into one.
    """
    if not url:
        return ''
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.strip().lower()
    host = parts.netloc.lower().removeprefix('www.')
    path = parts.path.rstrip('/').lower()
    return f'{host}{path}'


def location_token(location):
    """A coarse location token: state abbreviation, 'remote', or first city word."""
    text = (location or '').lower()
    if not text.strip():
        return ''
    if re.search(r'\bremote\b|\banywhere\b|work from home', text):
        return 'remote'
    state = re.search(r'\b([a-z]{2})\b\s*$', text.strip())
    if state:
        return state.group(1)
    return re.split(r'[,/|]', text)[0].strip()[:20]


def build_dedupe_key(job):
    """Stable identity for a posting, independent of which source found it."""
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    company = normalize_company(get('company'))
    title = normalize_title(get('title'))
    where = location_token(get('location'))
    if not company or not title:
        # Fall back to the URL so we at least dedupe re-discoveries.
        return normalize_url(get('job_url') or get('application_url')) or None
    return f'{company}|{title}|{where}'


def source_rank(source):
    return SOURCE_PRIORITY.get((source or '').lower(), 20)


def prefer(existing_source, new_source):
    """True when the new source is a more authoritative origin."""
    return source_rank(new_source) > source_rank(existing_source)
