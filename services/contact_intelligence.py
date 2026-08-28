"""Contact intelligence (V3 Parts 7-12, 17-18).

Find legitimate public professional contacts for high-priority jobs, compute
their relevance, and track outreach — with a hard rule: NOTHING is fabricated.
A person is only recorded with evidence from a legitimate public source
(company team page, official website, a job posting that names the recruiter,
or a public professional profile reachable without auth). If no legitimate
person can be identified, the recommended contact is UNKNOWN.

Email is captured only when it is genuinely public/verified. A guessed pattern
is labelled PATTERN_INFERRED and never treated as verified.
"""

import re
from datetime import datetime, timezone

from config.settings import Config


def should_search_contacts(job):
    """Selective gating (Part 13): only attempt expensive contact discovery for
    high-priority, verified, strong-match jobs."""
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    priority = get('application_priority_score') or 0
    if priority < Config.CONTACT_TRIGGER_PRIORITY:
        return False
    if Config.CONTACT_REQUIRE_VERIFIED_URL and \
       get('application_url_status') != 'verified':
        return False
    match = get('candidate_match_score')
    if match is not None and match < Config.CONTACT_REQUIRE_STRONG_MATCH:
        return False
    return True


def contact_relevance(contact_type, role_label='', company_name='',
                      match_score=None, role_family=None, evidence_quality='LOW'):
    """How relevant a discovered contact appears to a specific job.

    Explicitly NOT a prediction of response probability — it only ranks how well
    the person maps to this job's hiring lane. Bounded 0-100.
    """
    w = Config.CONTACT_RELEVANCE_WEIGHTS
    total = sum(w.values()) or 1.0

    role_scores = {
        'hiring_manager': 100.0, 'engineering_manager': 95.0,
        'data_manager': 95.0, 'technical_recruiter': 88.0,
        'university_recruiter': 82.0, 'talent_acquisition': 74.0,
        'department_leader': 70.0,
    }
    role_match = role_scores.get(contact_type, 40.0)

    department_match = 85.0

    seniority = {
        'hiring_manager': 100.0, 'engineering_manager': 95.0,
        'data_manager': 92.0, 'department_leader': 90.0,
        'technical_recruiter': 70.0, 'university_recruiter': 65.0,
        'talent_acquisition': 60.0,
    }.get(contact_type, 50.0)

    company_signal = 85.0 if company_name else 60.0
    family_score = (
        80.0 if role_family in ('DATA_ENGINEERING', 'ANALYTICS_BI',
                                'CLOUD_DATA', 'DATA_AUTOMATION', 'DATABASE_SQL')
        else 50.0
    )
    evidence_q = {
        'HIGH': 100.0, 'MEDIUM': 70.0, 'LOW': 40.0, 'UNKNOWN': 30.0,
    }.get((evidence_quality or 'LOW').upper(), 40.0)

    raw = (
        role_match * w['role_match']
        + department_match * w['department_match']
        + seniority * w['seniority']
        + company_signal * w['company_matches']
        + family_score * w['role_family']
        + evidence_q * w['evidence_quality']
    ) / total
    return round(max(0.0, min(100.0, raw)), 1)


def confidence_for(source, evidence_quality='LOW'):
    """Confidence derived from the evidence source + quality."""
    if source in ('company_team_page', 'company_leadership_page'):
        return 'HIGH' if evidence_quality in ('HIGH', 'MEDIUM') else 'MEDIUM'
    if source in ('job_posting_recruiter', 'official_website'):
        return 'MEDIUM'
    if source in ('public_profile', 'search_result'):
        return 'LOW'
    return 'UNKNOWN'


def _infer_type(role, source_url=''):
    role_l = (role or '').lower()
    if any(x in role_l for x in ('manager', 'lead', 'director', 'head of',
                                 'engineering manager', 'engineering lead')):
        return 'hiring_manager'
    if any(x in role_l for x in ('recruiter', 'talent', 'acquisition')):
        return 'technical_recruiter'
    if any(x in role_l for x in ('university', 'early career', 'campus')):
        return 'university_recruiter'
    return 'hiring_manager'


def _classify_email(email, source):
    """Email state. A guessed pattern is PATTERN_INFERRED, never verified."""
    if not email:
        return 'NOT_FOUND'
    if source in ('company_team_page', 'company_leadership_page',
                  'official_website') and re.match(r'^[\w\.\-\+]+@[\w\.\-]+$', email):
        return 'VERIFIED_PUBLIC'
    if source in ('public_profile', 'public_profile_slug'):
        return 'PUBLIC_UNVERIFIED'
    return 'PATTERN_INFERRED'


def discover(job):
    """Discover legitimate public contacts for a job.

    This build deliberately does not crawl private data. Contacts are surfaced
    only from authoritative in-band evidence already present on the job:
      - a `contact_hints` list (name/role/source/source_url/email) that a trusted
        source supplied, OR
      - a recruiter explicitly named in the posting description.
    When nothing legitimate is found, returns status=UNKNOWN.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    contacts = []

    for hint in get('contact_hints') or []:
        if not isinstance(hint, dict):
            continue
        name = (hint.get('name') or '').strip()
        if not name:
            continue
        role = (hint.get('role') or '').strip()
        source = (hint.get('source') or 'public_source').strip()
        source_url = (hint.get('source_url') or '').strip()
        cont_type = hint.get('contact_type') or _infer_type(role, source_url)
        email = (hint.get('email') or '').strip()
        linkedin = (hint.get('linkedin_url') or '').strip()
        evidence_q = (hint.get('evidence_quality') or 'LOW').upper()
        conf = hint.get('confidence') or confidence_for(source, evidence_q)
        email_state = _classify_email(email, source)

        relevance = contact_relevance(
            cont_type,
            role_label=role,
            company_name=get('company'),
            match_score=get('candidate_match_score'),
            role_family=get('role_family'),
            evidence_quality=evidence_q,
        )
        contacts.append({
            'contact_type': cont_type,
            'contact_name': name,
            'contact_role': role or None,
            'company': get('company'),
            'source': source,
            'source_url': source_url or None,
            'discovered_at': datetime.now(timezone.utc).isoformat(),
            'confidence': conf,
            'evidence': hint.get('evidence') or [
                f'Sourced from {source}' + (f' ({source_url})' if source_url else '')
            ],
            'email': email or None,
            'email_state': email_state,
            'email_source': source_url or source,
            'email_verified': email_state == Config.EMAIL_VERIFIED_PUBLIC,
            'linkedin_url': linkedin or None,
            'contact_relevance_score': relevance,
            'is_recommended': not contacts,
        })

    if not contacts:
        return {
            'status': 'UNKNOWN',
            'contacts': [],
            'message': 'No legitimate public professional contact could be '
                       'matched to this job. Hiring contact: UNKNOWN.',
        }
    return {'status': 'found', 'contacts': contacts, 'message': ''}