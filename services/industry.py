"""Industry classification and industry-opportunity intelligence (V3).

Industry is inferred from available evidence — the job's own text, the company
name, and any structured source metadata — NOT from the job-board category
alone. Classification is a research signal layered on top of the existing
matching/scoring pipeline; it never overrides a poor role match.

Under-the-radar means "outside the user's default high-volume target
industries", never a claim of low competition. Competition is shown only when
legitimate evidence exists and otherwise reported as UNKNOWN.
"""

from config.settings import Config
from services.text_utils import clean_html


def _industries():
    """All known industry labels (core + under-the-radar)."""
    seen = set(Config.CORE_INDUSTRIES)
    seen.update(Config.UNDER_THE_RADAR_INDUSTRIES)
    return list(seen)


def _matched_signal(title, description):
    """Find which industry + signal phrase matched the posting text."""
    text = f'{clean_html(title or "")} {clean_html(description or "")}'.lower()
    for industry in _industries():
        for sig in Config.INDUSTRY_SIGNALS.get(industry, []) or []:
            if sig in text:
                return industry, sig
    return None, None


def classify_industry(title='', description='', company='', source='',
                      metadata=None):
    """Infer a job's industry from available evidence.

    Returns a dict: {industry, label, industry_type, under_the_radar, evidence,
    matched_phrase}. Industry is a research/display signal; it never overrides
    a poor role match (that is the scoring engine's job).

    Signal order:
      1. Explicit industry keyword in the job text.
      2. Company-name keyword (corroborating only).
    When nothing matches, industry is UNKNOWN.
    """
    evidence = []
    matched, matched_sig = _matched_signal(title, description)

    # 2) Company-name corroboration (never sole evidence for a winnable claim).
    if matched is None:
        company_l = (company or '').lower()
        for industry in _industries():
            kw = next(
                (k for k in _COMPANY_KEYWORDS.get(industry, []) if k in company_l),
                None,
            )
            if kw:
                matched, matched_sig = industry, kw
                evidence.append(f'Company name mentions {kw}')
                break

    if matched is None or matched == Config.DEFAULT_INDUSTRY:
        return {
            'industry': 'UNKNOWN',
            'label': 'Unknown',
            'industry_type': 'UNKNOWN',
            'under_the_radar': False,
            'is_core': False,
            'under_the_radar_reason': None,
            'evidence': [],
            'matched_phrase': None,
        }

    label = Config.INDUSTRY_LABELS.get(matched, matched)
    under_the_radar = matched in Config.UNDER_THE_RADAR_INDUSTRIES
    evidence.append(f'Matched "{matched_sig}" in posting text/company')

    return {
        'industry': matched,
        'label': label,
        'industry_type': (
            'UNDER-THE-RADAR' if under_the_radar
            else 'CORE' if matched in Config.CORE_INDUSTRIES
            else 'UNKNOWN'
        ),
        'under_the_radar': under_the_radar,
        'is_core': matched in Config.CORE_INDUSTRIES,
        'under_the_radar_reason': (
            'This job belongs to an industry outside your default high-volume '
            'target industries.'
            if under_the_radar else None
        ),
        'evidence': evidence,
        'matched_phrase': matched_sig,
    }


_COMPANY_KEYWORDS = {
    'FINANCE': ['bank', 'capital', 'financial', 'fidelity', 'jpmorgan', 'goldman',
                'investment', 'wells fargo', 'bofa'],
    'HEALTHCARE': ['health', 'hospital', 'clinic', 'pharma', 'biogen', 'pfizer',
                   'unitedhealth', 'optum', 'aetna'],
    'TECHNOLOGY': ['software', 'cloud', 'data', 'digital', 'datadog', 'snowflake',
                   'databricks', 'amazon', 'microsoft', 'google', 'oracle'],
    'INSURANCE': ['insurance', 'liberty mutual', 'nationwide', 'allstate',
                  'progressive'],
    'CONSULTING': ['consulting', 'deloitte', 'accenture', 'mckinsey', 'kpmg',
                   'pwc', 'ey', 'bain'],
    'MANUFACTURING': ['manufactur', 'industrial', 'automotive', 'bosch',
                      'tesla', 'caterpillar'],
    'ENERGY': ['energy', 'exelon', 'edison', 'duke energy', 'solar', 'schneider',
               'shell', 'chevron'],
    'RETAIL': ['retail', 'ecommerce', 'walmart', 'shopify'],
    'FOOD': ['food', 'kroger', 'pepsi', 'nestle', 'general mills'],
}


def industry_opportunity(db, Job, industry, days=30, limit=100):
    """Aggregate opportunity statistics for one industry from the live pool.

    Every number comes from stored, non-hidden, non-expired, non-duplicate
    jobs in the industry. Candidate-competition figures are only included when
    `competition_signal` is legitimately set; otherwise competition is UNKNOWN.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import or_

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = (
        Job.query.filter(
            Job.industry == industry,
            Job.is_hidden.is_(False),
            Job.is_expired.is_(False),
            Job.duplicate_of_id.is_(None),
            or_(Job.date_scraped >= cutoff, Job.date_posted >= cutoff),
        ).all()
    )
    if not jobs:
        return {
            'industry': industry,
            'label': Config.INDUSTRY_LABELS.get(industry, industry),
            'count': 0, 'fresh_jobs': 0, 'companies': 0,
            'target_role_family_jobs': 0, 'entry_level_jobs': 0,
            'url_verify_rate': None, 'authorization_evidence_rate': None,
            'competition': 'UNKNOWN', 'opportunity': 'UNKNOWN',
            'opportunity_score': None,
        }

    fresh = sum(
        1 for j in jobs if (j.freshness_bucket or 'unknown') in ('hot', 'fresh')
    )
    companies = len({j.company for j in jobs if j.company})
    target_family = sum(
        1 for j in jobs
        if j.role_family in ('CLOUD_DATA', 'DATA_AUTOMATION', 'DATABASE_SQL',
                              'DATA_QUALITY', 'DATA_ENGINEERING', 'ANALYTICS_BI')
    )
    entry = sum(1 for j in jobs if (j.role_tier or 3) in (1, 2))
    with_url = [j for j in jobs if j.application_url]
    verified_rate = (
        round(sum(1 for j in with_url if j.application_url_status == 'verified')
              / len(with_url) * 100, 1) if with_url else None
    )
    auth_known = sum(
        1 for j in jobs if (j.sponsorship_status or 'unknown') != 'unknown'
    )
    auth_rate = round(auth_known / len(jobs) * 100, 1) if jobs else None

    competition = _aggregate_competition(jobs)

    score = _industry_opportunity_score(
        matching=len(jobs), fresh=fresh, entry=entry, target_family=target_family,
        verify_rate=verified_rate, auth_rate=auth_rate, competition=competition,
    )
    return {
        'industry': industry,
        'label': Config.INDUSTRY_LABELS.get(industry, industry),
        'count': len(jobs),
        'fresh_jobs': fresh,
        'companies': companies,
        'target_role_family_jobs': target_family,
        'entry_level_jobs': entry,
        'url_verify_rate': verified_rate,
        'authorization_evidence_rate': auth_rate,
        'competition': competition,
        'opportunity': _opportunity_level(score),
        'opportunity_score': score,
        'note': 'Values reflect stored scored jobs only. Competition is UNKNOWN '
                'unless supported by actual evidence.',
    }


def _aggregate_competition(jobs):
    """Combine per-job competition signals; UNKNOWN unless real data exists."""
    signals = {j.competition_signal for j in jobs if j.competition_signal}
    if not signals:
        return 'UNKNOWN'
    ranked = {'LOW': 1, 'MODERATE': 2, 'HIGH': 3, 'VERY_HIGH': 4}
    present = [ranked[s] for s in signals if s in ranked]
    if not present:
        return 'UNKNOWN'
    avg = sum(present) / len(present)
    if avg < 1.5:
        return 'LOW'
    if avg < 2.5:
        return 'MODERATE'
    if avg < 3.5:
        return 'HIGH'
    return 'VERY_HIGH'


def _industry_opportunity_score(matching, fresh, target_family, entry,
                                verify_rate, auth_rate, competition):
    weights = Config.INDUSTRY_OPPORTUNITY_WEIGHTS
    total_weight = sum(weights.values()) or 1.0
    min_jobs = max(1, Config.INDUSTRY_OPPORTUNITY_MIN_JOBS)

    matching_sig = min(1.0, matching / min_jobs)
    fresh_sig = min(1.0, fresh / min_jobs)
    target_sig = min(1.0, target_family / max(1, matching)) if target_family else 0.0
    entry_sig = min(1.0, entry / max(1, matching)) if entry else 0.0
    verify_sig = (verify_rate or 0) / 100.0
    auth_sig = (auth_rate or 0) / 100.0
    comp_sig = _comp_signal_to_score(competition)

    raw = (
        matching_sig * weights['matching_job_count']
        + fresh_sig * weights['fresh_jobs']
        + target_sig * weights['target_role_family_jobs']
        + entry_sig * weights['entry_level_jobs']
        + verify_sig * weights['url_verify_rate']
        + auth_sig * weights['authorization_evidence_rate']
        + comp_sig * weights['competition']
    ) / total_weight
    return round(max(0.0, min(100.0, raw * 100.0)), 1)


def _comp_signal_to_score(competition):
    return {'LOW': 1.0, 'MODERATE': 0.7, 'HIGH': 0.4, 'VERY_HIGH': 0.2}.get(
        (competition or 'UNKNOWN'), 0.5
    )


def _opportunity_level(score):
    if score is None:
        return 'UNKNOWN'
    if score >= 70:
        return 'HIGH'
    if score >= 45:
        return 'MEDIUM'
    return 'LOW'