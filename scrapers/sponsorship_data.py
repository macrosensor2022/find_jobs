"""
Sponsorship & E-Verify data ingestion and employer lookup.

Loads public US government datasets into SQLite for offline matching.

Usage:
    python -m scrapers.sponsorship_data --load-everify data/everify_employers.csv
    python -m scrapers.sponsorship_data --load-lca data/h1b_disclosure.csv

Data sources documented in data_sources.md.
"""

import csv
import re
import os
import sys
import logging
import argparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company name normalization
# ---------------------------------------------------------------------------

_LEGAL_SUFFIX_RE = re.compile(
    r',?\s*\b(inc|incorporated|llc|llp|corp|corporation|'
    r'co|company|ltd|limited|plc|lp)\b\.?',
    re.IGNORECASE,
)
_LEADING_THE_RE = re.compile(r'^the\s+', re.IGNORECASE)
_PUNCT_RE = re.compile(r'[^\w\s]')
_WS_RE = re.compile(r'\s+')


def normalize_company_name(name: str) -> str:
    """Normalize an employer name for matching.

    Lowercase, strip common legal suffixes (Inc, LLC, Corp, etc.),
    remove leading "The", strip punctuation, collapse whitespace.
    """
    if not name:
        return ''
    result = name.lower().strip()
    result = _LEGAL_SUFFIX_RE.sub('', result)
    result = _LEADING_THE_RE.sub('', result)
    result = _PUNCT_RE.sub(' ', result)
    result = _WS_RE.sub(' ', result).strip()
    return result


# ---------------------------------------------------------------------------
# Employer lookup
# ---------------------------------------------------------------------------

def lookup_employer(company_name, db_session, confidence_threshold=80):
    """Look up an employer in the E-Verify and sponsor_history tables.

    Returns a dict:
        is_everify            – True, or None (unknown)
        h1b_lca_count         – int or None
        median_wage           – int or None
        wage_level            – int or None
        employer_match_conf   – 0.0–1.0 or None

    Below the confidence threshold values are left as None (unknown)
    rather than guessing, per the spec guardrails.
    """
    from backend.models import EVerifyEmployer, SponsorHistory

    result = {
        'is_everify': None,
        'h1b_lca_count': None,
        'median_wage': None,
        'wage_level': None,
        'employer_match_conf': None,
    }

    normalized = normalize_company_name(company_name)
    if not normalized:
        return result

    # --- Exact match (indexed) ---------------------------------------------------
    ev = db_session.query(EVerifyEmployer).filter_by(
        normalized_name=normalized,
    ).first()
    if ev:
        result['is_everify'] = True
        result['employer_match_conf'] = 1.0

    sh = (
        db_session.query(SponsorHistory)
        .filter_by(normalized_name=normalized)
        .order_by(SponsorHistory.fiscal_year.desc())
        .first()
    )
    if sh:
        result['h1b_lca_count'] = sh.lca_count
        result['median_wage'] = sh.median_wage
        result['wage_level'] = sh.prevailing_wage_level
        if result['employer_match_conf'] is None:
            result['employer_match_conf'] = 1.0

    if result['employer_match_conf'] is not None:
        return result

    # --- Fuzzy match via rapidfuzz ------------------------------------------------
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        logger.warning("rapidfuzz not installed; skipping fuzzy employer match")
        return result

    ev_names = [
        r[0] for r in
        db_session.query(EVerifyEmployer.normalized_name).distinct().all()
    ]
    if ev_names:
        best = process.extractOne(
            normalized, ev_names, scorer=fuzz.token_set_ratio,
        )
        if best and best[1] >= confidence_threshold:
            result['is_everify'] = True
            result['employer_match_conf'] = round(best[1] / 100.0, 2)

    sh_names = [
        r[0] for r in
        db_session.query(SponsorHistory.normalized_name).distinct().all()
    ]
    if sh_names:
        top_matches = process.extract(
            normalized, sh_names, scorer=fuzz.token_set_ratio, limit=10,
        )
        qualifying = [m for m in top_matches if m[1] >= confidence_threshold]
        if qualifying:
            best_score = qualifying[0][1]
            tied = [m[0] for m in qualifying if m[1] == best_score]
            sh_row = (
                db_session.query(SponsorHistory)
                .filter(SponsorHistory.normalized_name.in_(tied))
                .order_by(SponsorHistory.lca_count.desc(),
                          SponsorHistory.fiscal_year.desc())
                .first()
            )
            if sh_row:
                result['h1b_lca_count'] = sh_row.lca_count
                result['median_wage'] = sh_row.median_wage
                result['wage_level'] = sh_row.prevailing_wage_level
                conf = round(best_score / 100.0, 2)
                if result['employer_match_conf'] is None or conf > result['employer_match_conf']:
                    result['employer_match_conf'] = conf

    return result


# ---------------------------------------------------------------------------
# Batch employer lookup (avoids N x M fuzzy scans during refresh)
# ---------------------------------------------------------------------------

def batch_lookup_employers(company_names, db_session, confidence_threshold=80):
    """Look up many employers at once, sharing a single fuzzy index.

    Returns a dict mapping each input name to the same result dict
    that lookup_employer() returns.
    """
    from backend.models import EVerifyEmployer, SponsorHistory

    normalized_map = {}
    for name in company_names:
        normalized_map.setdefault(normalize_company_name(name), []).append(name)

    unique_norms = list(normalized_map.keys())
    results = {name: {
        'is_everify': None, 'h1b_lca_count': None, 'median_wage': None,
        'wage_level': None, 'employer_match_conf': None,
    } for name in company_names}

    ev_set = {
        r[0] for r in
        db_session.query(EVerifyEmployer.normalized_name).distinct().all()
    }

    sh_rows_by_norm = {}
    for sh in (db_session.query(SponsorHistory)
               .order_by(SponsorHistory.lca_count.desc()).all()):
        sh_rows_by_norm.setdefault(sh.normalized_name, sh)

    sh_name_set = set(sh_rows_by_norm.keys())

    fuzzy_cache = {}

    try:
        from rapidfuzz import process, fuzz
        ev_list = list(ev_set) if ev_set else []
        sh_list = list(sh_name_set) if sh_name_set else []
        has_rapidfuzz = True
    except ImportError:
        has_rapidfuzz = False
        ev_list = []
        sh_list = []

    for norm in unique_norms:
        if not norm:
            continue

        r = {
            'is_everify': None, 'h1b_lca_count': None, 'median_wage': None,
            'wage_level': None, 'employer_match_conf': None,
        }

        if norm in ev_set:
            r['is_everify'] = True
            r['employer_match_conf'] = 1.0

        if norm in sh_rows_by_norm:
            sh = sh_rows_by_norm[norm]
            r['h1b_lca_count'] = sh.lca_count
            r['median_wage'] = sh.median_wage
            r['wage_level'] = sh.prevailing_wage_level
            if r['employer_match_conf'] is None:
                r['employer_match_conf'] = 1.0

        if r['employer_match_conf'] is None and has_rapidfuzz:
            if norm not in fuzzy_cache:
                ev_best = (process.extractOne(norm, ev_list, scorer=fuzz.token_set_ratio)
                           if ev_list else None)
                sh_best_matches = (process.extract(norm, sh_list, scorer=fuzz.token_set_ratio, limit=10)
                                   if sh_list else [])
                fuzzy_cache[norm] = (ev_best, sh_best_matches)

            ev_best, sh_best_matches = fuzzy_cache[norm]

            if ev_best and ev_best[1] >= confidence_threshold:
                r['is_everify'] = True
                r['employer_match_conf'] = round(ev_best[1] / 100.0, 2)

            qualifying = [m for m in sh_best_matches if m[1] >= confidence_threshold]
            if qualifying:
                best_score = qualifying[0][1]
                tied_names = [m[0] for m in qualifying if m[1] == best_score]
                sh = None
                for tn in tied_names:
                    if tn in sh_rows_by_norm:
                        if sh is None or sh_rows_by_norm[tn].lca_count > (sh.lca_count or 0):
                            sh = sh_rows_by_norm[tn]
                if sh:
                    r['h1b_lca_count'] = sh.lca_count
                    r['median_wage'] = sh.median_wage
                    r['wage_level'] = sh.prevailing_wage_level
                    conf = round(best_score / 100.0, 2)
                    if r['employer_match_conf'] is None or conf > r['employer_match_conf']:
                        r['employer_match_conf'] = conf

        for orig_name in normalized_map[norm]:
            results[orig_name] = r

    return results


# ---------------------------------------------------------------------------
# CSV column auto-detection
# ---------------------------------------------------------------------------

_EV_NAME  = ['company name', 'employer name', 'organization name', 'name', 'company']
_EV_CITY  = ['city', 'physical city', 'physical address city']
_EV_STATE = ['state', 'physical state', 'physical address state']

_LCA_NAME     = ['employer', 'employer name', 'petitioner name', 'company name', 'employer_name']
_LCA_YEAR     = ['fiscal year', 'fiscal_year', 'year', 'fy']
_LCA_COUNT    = ['initial approvals', 'initial approval', 'lca_count', 'petitions']
_LCA_APPROVAL = ['initial approvals', 'initial approval', 'approvals']
_LCA_DENIAL   = ['initial denials', 'initial denial', 'denials']
_LCA_WAGE     = ['median wage', 'median_wage', 'average annual wage', 'avg annual wage']
_LCA_LEVEL    = ['prevailing wage level', 'wage level', 'prevailing_wage_level', 'pw_level']


def _find_col(headers, candidates):
    """Return the first header matching any candidate (case-insensitive)."""
    lower_map = {h.lower().strip(): h for h in headers}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _safe_int(val):
    """Parse an integer from a possibly comma-formatted string."""
    if not val:
        return None
    try:
        return int(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def load_everify_csv(csv_path, db_session, batch_size=5000):
    """Load an E-Verify employer list CSV into the everify_employer table."""
    from backend.models import EVerifyEmployer

    if not os.path.exists(csv_path):
        logger.error(f"File not found: {csv_path}")
        return 0

    count = 0
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        name_col  = _find_col(headers, _EV_NAME)
        city_col  = _find_col(headers, _EV_CITY)
        state_col = _find_col(headers, _EV_STATE)

        if not name_col:
            logger.error(
                f"Cannot find employer name column in {csv_path}. "
                f"Headers: {headers}"
            )
            return 0

        batch = []
        for row in reader:
            employer_name = (row.get(name_col) or '').strip()
            if not employer_name:
                continue
            batch.append(EVerifyEmployer(
                employer_name=employer_name,
                normalized_name=normalize_company_name(employer_name),
                city=(row.get(city_col) or '').strip() if city_col else None,
                state=(row.get(state_col) or '').strip() if state_col else None,
            ))
            count += 1
            if len(batch) >= batch_size:
                db_session.bulk_save_objects(batch)
                db_session.commit()
                batch = []
        if batch:
            db_session.bulk_save_objects(batch)
            db_session.commit()

    logger.info(f"Loaded {count} E-Verify employers from {csv_path}")
    return count


def load_lca_csv(csv_path, db_session, batch_size=5000):
    """Legacy CSV loader — kept for pre-aggregated data-hub CSVs."""
    from backend.models import SponsorHistory

    if not os.path.exists(csv_path):
        logger.error(f"File not found: {csv_path}")
        return 0

    count = 0
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        name_col     = _find_col(headers, _LCA_NAME)
        year_col     = _find_col(headers, _LCA_YEAR)
        count_col    = _find_col(headers, _LCA_COUNT)
        approval_col = _find_col(headers, _LCA_APPROVAL)
        denial_col   = _find_col(headers, _LCA_DENIAL)
        wage_col     = _find_col(headers, _LCA_WAGE)
        level_col    = _find_col(headers, _LCA_LEVEL)

        if not name_col:
            logger.error(
                f"Cannot find employer name column in {csv_path}. "
                f"Headers: {headers}"
            )
            return 0

        batch = []
        for row in reader:
            employer_name = (row.get(name_col) or '').strip()
            if not employer_name:
                continue

            approvals = _safe_int(row.get(approval_col)) if approval_col else None
            denials   = _safe_int(row.get(denial_col)) if denial_col else None
            lca_count = _safe_int(row.get(count_col)) if count_col else None
            if lca_count is None and approvals is not None:
                lca_count = (approvals or 0) + (denials or 0)

            batch.append(SponsorHistory(
                employer_name=employer_name,
                normalized_name=normalize_company_name(employer_name),
                fiscal_year=_safe_int(row.get(year_col)) if year_col else None,
                lca_count=lca_count,
                approvals=approvals,
                denials=denials,
                median_wage=_safe_int(row.get(wage_col)) if wage_col else None,
                prevailing_wage_level=_safe_int(row.get(level_col)) if level_col else None,
            ))
            count += 1
            if len(batch) >= batch_size:
                db_session.bulk_save_objects(batch)
                db_session.commit()
                batch = []
        if batch:
            db_session.bulk_save_objects(batch)
            db_session.commit()

    logger.info(f"Loaded {count} H-1B sponsor records from {csv_path}")
    return count


# ---------------------------------------------------------------------------
# DOL LCA Disclosure XLSX loader (row-level → aggregated per employer)
# ---------------------------------------------------------------------------

_UNIT_MULTIPLIER = {
    'HOUR': 2080,
    'WEEK': 52,
    'BI-WEEKLY': 26,
    'MONTH': 12,
    'YEAR': 1,
}

_LEVEL_MAP = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}


def load_lca_xlsx(xlsx_path, db_session, fiscal_year=2026, batch_size=5000):
    """Load a DOL LCA Disclosure XLSX into sponsor_history.

    Reads with openpyxl read_only mode, aggregates per normalized employer,
    and upserts into SponsorHistory.

    Expected columns (DOL standard names):
        EMPLOYER_NAME, CASE_STATUS, WAGE_RATE_OF_PAY_FROM,
        WAGE_UNIT_OF_PAY, PW_WAGE_LEVEL
    """
    import openpyxl
    from collections import defaultdict, Counter
    from statistics import median
    from backend.models import SponsorHistory

    if not os.path.exists(xlsx_path):
        logger.error(f"File not found: {xlsx_path}")
        return 0

    logger.info(f"Opening {xlsx_path} (read-only)…")
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter)
    headers = [str(h).strip().upper() if h else '' for h in raw_headers]
    col = {h: i for i, h in enumerate(headers) if h}

    name_idx   = col.get('EMPLOYER_NAME')
    status_idx = col.get('CASE_STATUS')
    wage_idx   = col.get('WAGE_RATE_OF_PAY_FROM')
    unit_idx   = col.get('WAGE_UNIT_OF_PAY')
    level_idx  = col.get('PW_WAGE_LEVEL')

    if name_idx is None:
        logger.error(f"EMPLOYER_NAME not found. First 30 headers: {headers[:30]}")
        wb.close()
        return 0

    employers = defaultdict(lambda: {
        'raw_name': '',
        'lca_count': 0,
        'approvals': 0,
        'denials': 0,
        'wages': [],
        'levels': [],
    })

    total_rows = 0
    skipped = 0

    for row in rows_iter:
        if name_idx >= len(row):
            continue
        raw_name = row[name_idx]
        if not raw_name or not str(raw_name).strip():
            skipped += 1
            continue

        raw_name = str(raw_name).strip()
        norm = normalize_company_name(raw_name)
        if not norm:
            skipped += 1
            continue

        total_rows += 1
        emp = employers[norm]
        if not emp['raw_name']:
            emp['raw_name'] = raw_name

        emp['lca_count'] += 1

        status = ''
        if status_idx is not None and status_idx < len(row) and row[status_idx]:
            status = str(row[status_idx]).strip().upper()
        if status.startswith('CERTIFIED'):
            emp['approvals'] += 1
        elif status == 'DENIED':
            emp['denials'] += 1

        if wage_idx is not None and wage_idx < len(row) and row[wage_idx]:
            try:
                wage_raw = str(row[wage_idx]).replace(',', '').replace('$', '').strip()
                wage = float(wage_raw)
                unit = 'YEAR'
                if unit_idx is not None and unit_idx < len(row) and row[unit_idx]:
                    unit = str(row[unit_idx]).strip().upper()
                    if 'BI' in unit and 'WEEK' in unit:
                        unit = 'BI-WEEKLY'
                multiplier = _UNIT_MULTIPLIER.get(unit, 1)
                annual = wage * multiplier
                if 10_000 < annual < 1_000_000:
                    emp['wages'].append(annual)
            except (ValueError, TypeError):
                pass

        if level_idx is not None and level_idx < len(row) and row[level_idx]:
            level_str = str(row[level_idx]).strip().upper()
            # Extract roman numeral: "Level III - $120,000" → "III"
            after_level = level_str.split('LEVEL')[-1].strip()
            roman = after_level.split('-')[0].split('$')[0].split('(')[0].strip()
            if roman in _LEVEL_MAP:
                emp['levels'].append(_LEVEL_MAP[roman])

        if total_rows % 50_000 == 0:
            logger.info(f"  … processed {total_rows:,} rows, {len(employers):,} employers")

    wb.close()
    logger.info(
        f"Parsed {total_rows:,} LCA rows → {len(employers):,} unique employers "
        f"(skipped {skipped:,} blank)"
    )

    new_count = 0
    updated_count = 0
    batch = []

    for norm, data in employers.items():
        median_wage = int(median(data['wages'])) if data['wages'] else None
        wage_level = Counter(data['levels']).most_common(1)[0][0] if data['levels'] else None

        existing = db_session.query(SponsorHistory).filter_by(
            normalized_name=norm, fiscal_year=fiscal_year,
        ).first()

        if existing:
            existing.employer_name = data['raw_name']
            existing.lca_count = data['lca_count']
            existing.approvals = data['approvals']
            existing.denials = data['denials']
            existing.median_wage = median_wage
            existing.prevailing_wage_level = wage_level
            updated_count += 1
        else:
            batch.append(SponsorHistory(
                employer_name=data['raw_name'],
                normalized_name=norm,
                fiscal_year=fiscal_year,
                lca_count=data['lca_count'],
                approvals=data['approvals'],
                denials=data['denials'],
                median_wage=median_wage,
                prevailing_wage_level=wage_level,
            ))
            new_count += 1

            if len(batch) >= batch_size:
                db_session.bulk_save_objects(batch)
                db_session.commit()
                batch = []

    if batch:
        db_session.bulk_save_objects(batch)
    db_session.commit()

    logger.info(f"SponsorHistory FY{fiscal_year}: {new_count:,} new, {updated_count:,} updated")
    return new_count + updated_count


# ---------------------------------------------------------------------------
# CLI:  python -m scrapers.sponsorship_data --load-everify ...
# ---------------------------------------------------------------------------

def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description='Load E-Verify and H-1B sponsorship data into JobTracker',
    )
    parser.add_argument('--load-everify', metavar='CSV',
                        help='Path to E-Verify employer list CSV')
    parser.add_argument('--load-lca', metavar='FILE',
                        help='Path to H-1B LCA file (.xlsx DOL disclosure or .csv data hub)')
    parser.add_argument('--clear', action='store_true',
                        help='Clear existing records in target table(s) before loading')
    args = parser.parse_args()

    if not args.load_everify and not args.load_lca:
        parser.print_help()
        sys.exit(1)

    from backend.models import db, EVerifyEmployer, SponsorHistory
    from config.settings import Config

    # Reuse the same Flask app as the main backend so we hit the same DB.
    from backend.app import app

    with app.app_context():
        db.create_all()

        if args.clear:
            if args.load_everify:
                EVerifyEmployer.query.delete()
                logger.info("Cleared everify_employer table")
            if args.load_lca:
                SponsorHistory.query.delete()
                logger.info("Cleared sponsor_history table")
            db.session.commit()

        if args.load_everify:
            n = load_everify_csv(args.load_everify, db.session)
            print(f"Loaded {n} E-Verify employers")

        if args.load_lca:
            path = args.load_lca
            if path.lower().endswith('.xlsx'):
                n = load_lca_xlsx(path, db.session)
            else:
                n = load_lca_csv(path, db.session)
            print(f"Loaded {n} H-1B sponsor records")


if __name__ == '__main__':
    main()
