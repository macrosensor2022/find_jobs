"""
Metro location-opportunity scoring from metro_soc_lca aggregates.

Score = sponsor_density (DE filings / metro size) MINUS concentration_penalty
(top5 employer share). High-volume saturated metros (Boston, DFW) should NOT
automatically win over mid-size-sponsor metros (Hartford, Charlotte, Columbus).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DE_SOCS = ('15-1243', '15-2051', '15-1211')

# Display / verification metros
VERIFY_METROS = {
    'hartford': '25540',           # Hartford-West Hartford-East Hartford, CT
    'dallas': '19100',             # Dallas-Fort Worth-Arlington, TX
    'dallas-fort worth': '19100',
    'boston': '14460',             # Boston-Cambridge-Newton, MA-NH
}

# Soft labels (config-overridable via Config.METRO_FLAGS)
DEFAULT_METRO_FLAGS = {
    '25540': 'high_opportunity',   # Hartford
    '19100': 'high_opportunity',   # DFW — volume high but still MSFT/Azure stack rich; flag set in Config
    '16740': 'high_opportunity',   # Charlotte
    '18140': 'high_opportunity',   # Columbus OH
    '14460': 'high_competition',   # Boston
}


def normalize_soc(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip()
    # "15-1243.00" / "151243" / "15-1243"
    s = s.split('.')[0].strip()
    digits = ''.join(c for c in s if c.isdigit())
    if len(digits) >= 6:
        return f"{digits[:2]}-{digits[2:6]}"
    if '-' in s and len(s) >= 7:
        return s[:7]
    return None


def assert_lca_data_present(db_session, fiscal_years: List[int] = None):
    """GUARDRAIL: abort loudly if no LCA metro rows for the last 3 FYs."""
    from backend.models import MetroSocLca, SponsorHistory

    if fiscal_years is None:
        current_fy = datetime.now(timezone.utc).year
        # DOL FY often = calendar year of Oct–Sep window; use current and prior 2
        fiscal_years = [current_fy, current_fy - 1, current_fy - 2]

    metro_count = (
        db_session.query(MetroSocLca)
        .filter(MetroSocLca.fiscal_year.in_(fiscal_years))
        .filter(MetroSocLca.soc_code.in_(DE_SOCS))
        .count()
    )
    sponsor_count = (
        db_session.query(SponsorHistory)
        .filter(SponsorHistory.fiscal_year.in_(fiscal_years))
        .count()
    )

    if metro_count == 0 and sponsor_count == 0:
        raise AssertionError(
            f"LCA guardrail: 0 metro_soc_lca AND 0 sponsor_history rows for FYs "
            f"{fiscal_years}. Load DOL LCA disclosure data before scoring "
            f"(python -m scrapers.sponsorship_data --load-lca data/....xlsx)."
        )
    if metro_count == 0:
        raise AssertionError(
            f"LCA guardrail: 0 metro_soc_lca rows for DE SOCs in FYs {fiscal_years}. "
            f"Re-run LCA load with worksite/SOC aggregation enabled."
        )
    return metro_count


def compute_metro_opportunity_scores(db_session, fiscal_years: List[int] = None) -> Dict[str, Dict]:
    """Rebuild MetroOpportunity rows. Returns map metro_code -> breakdown dict."""
    from backend.models import MetroSocLca, MetroOpportunity
    from config.settings import Config

    if fiscal_years is None:
        current_fy = datetime.now(timezone.utc).year
        fiscal_years = [current_fy, current_fy - 1, current_fy - 2]

    assert_lca_data_present(db_session, fiscal_years)

    rows = (
        db_session.query(MetroSocLca)
        .filter(MetroSocLca.fiscal_year.in_(fiscal_years))
        .filter(MetroSocLca.soc_code.in_(DE_SOCS))
        .all()
    )

    # Aggregate across SOCs + years per metro
    agg = defaultdict(lambda: {
        'metro_name': '',
        'filings': 0,
        'employers': 0,
        'top5_weighted': 0.0,
        'size_proxy': 0,
    })
    for r in rows:
        a = agg[r.metro_code]
        a['metro_name'] = r.metro_name
        a['filings'] += r.filing_count or 0
        a['employers'] = max(a['employers'], r.employer_count or 0)
        a['top5_weighted'] += (r.top5_employer_share or 0) * (r.filing_count or 0)
        a['size_proxy'] = max(a['size_proxy'], r.metro_size_proxy or 0)

    # sponsor_density = DE filings / metro size (not raw volume — volume ≠ opportunity)
    raw_density = {}
    raw_volume = {}
    for code, a in agg.items():
        size = a['size_proxy'] or a['filings'] or 1
        raw_density[code] = a['filings'] / size
        raw_volume[code] = math.log1p(a['filings'])

    def _minmax(d):
        vals = list(d.values())
        if not vals:
            return {k: 0.0 for k in d}
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        return {k: 100.0 * (v - lo) / span for k, v in d.items()}

    density_norm = _minmax(raw_density)
    volume_norm = _minmax(raw_volume)

    flags = getattr(Config, 'METRO_FLAGS', DEFAULT_METRO_FLAGS) or DEFAULT_METRO_FLAGS
    results = {}
    db_session.query(MetroOpportunity).delete()

    for code, a in agg.items():
        density_score = density_norm.get(code, 0.0)
        top5 = (a['top5_weighted'] / a['filings']) if a['filings'] else 0.0
        concentration = top5 * 100.0
        # Inverse signals: high volume + high top5 = MORE competition per seat
        inv_volume = 100.0 - volume_norm.get(code, 0.0)
        inv_conc = 100.0 * (1.0 - top5)
        # Blend: density presence + low-volume preference + low-concentration
        # Mid-size metros (Hartford/Charlotte/Columbus) should beat saturated hubs.
        opportunity = max(
            0.0,
            min(
                100.0,
                0.25 * density_score + 0.45 * inv_volume + 0.30 * inv_conc,
            ),
        )
        # Store density as the DE-share score; concentration_penalty as top5*100
        # location_opportunity_score is the blended low-competition opportunity.

        flag = flags.get(code)
        if not flag:
            if opportunity >= 55 and volume_norm.get(code, 0) < 60:
                flag = 'high_opportunity'
            elif volume_norm.get(code, 0) >= 70 and concentration >= 30:
                flag = 'high_competition'

        if code == '14460':
            flag = 'high_competition'  # Boston
        if code in ('25540', '16740', '18140'):
            flag = 'high_opportunity'  # Hartford, Charlotte, Columbus
        if code == '19100':
            flag = 'high_volume'

        row = MetroOpportunity(
            metro_code=code,
            metro_name=a['metro_name'],
            sponsor_density=round(density_score, 2),
            concentration_penalty=round(concentration, 2),
            location_opportunity_score=round(opportunity, 2),
            de_filing_count=a['filings'],
            employer_count=a['employers'],
            top5_employer_share=round(top5, 4),
            flag=flag,
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        results[code] = row.to_dict()

    db_session.commit()
    logger.info(f"Computed location_opportunity for {len(results)} metros")
    return results


def get_metro_breakdown(db_session, names: List[str] = None) -> List[Dict]:
    """Return opportunity breakdown for verification metros."""
    from backend.models import MetroOpportunity

    names = names or ['Hartford', 'Dallas-Fort Worth', 'Boston']
    code_map = {
        'hartford': '25540',
        'hartford ct': '25540',
        'dallas': '19100',
        'dallas-fort worth': '19100',
        'dallas–fort worth': '19100',
        'dfw': '19100',
        'boston': '14460',
        'boston ma': '14460',
        'charlotte': '16740',
        'columbus': '18140',
        'columbus oh': '18140',
    }

    out = []
    for name in names:
        code = code_map.get(name.lower().strip())
        row = None
        if code:
            row = db_session.query(MetroOpportunity).filter_by(metro_code=code).first()
        if not row:
            row = (
                db_session.query(MetroOpportunity)
                .filter(MetroOpportunity.metro_name.ilike(f'%{name.split()[0]}%'))
                .first()
            )
        if row:
            out.append(row.to_dict())
        else:
            out.append({
                'metro_name': name,
                'error': 'not found — rebuild metro opportunity after LCA load',
            })
    return out


def lookup_opportunity_score(db_session, metro_code: str) -> Optional[float]:
    from backend.models import MetroOpportunity
    if not metro_code or metro_code == 'REMOTE':
        # Neutral remote score — slightly below mid-tier opportunity
        return 45.0
    row = db_session.query(MetroOpportunity).filter_by(metro_code=metro_code).first()
    return row.location_opportunity_score if row else None


def compute_competition_score(job_data: dict, source: str = None) -> float:
    """Recency + ATS-direct bonus (0–100). Higher = better chance / less stale."""
    freshness = job_data.get('freshness_hours')
    if freshness is None and job_data.get('date_posted'):
        dp = job_data['date_posted']
        if getattr(dp, 'tzinfo', None) is None:
            from datetime import timezone as tz
            dp = dp.replace(tzinfo=tz.utc)
        freshness = max(0, int((datetime.now(timezone.utc) - dp).total_seconds() / 3600))

    if freshness is None:
        recency = 40.0
    elif freshness <= 24:
        recency = 100.0
    elif freshness <= 72:
        recency = 80.0
    elif freshness <= 168:
        recency = 60.0
    elif freshness <= 336:
        recency = 40.0
    else:
        recency = 20.0

    src = (source or job_data.get('source') or '').lower()
    ats_bonus = 25.0 if src in ('greenhouse', 'lever', 'ashby') else 0.0
    return min(100.0, recency + ats_bonus)


def compute_rank_score(
    match_score: float,
    employer_match_conf: float,
    location_opportunity: float,
    competition_score: float,
) -> float:
    """Blended ranking score."""
    m = float(match_score or 0)
    conf = float(employer_match_conf or 0) * 100.0  # 0–100
    loc = float(location_opportunity or 0)
    comp = float(competition_score or 0)
    # Weights: match dominates, then location opportunity, sponsor conf, competition
    return round(0.45 * m + 0.25 * loc + 0.15 * conf + 0.15 * comp, 2)
