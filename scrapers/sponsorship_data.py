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
            normalized, ev_names, scorer=fuzz.token_sort_ratio,
        )
        if best and best[1] >= confidence_threshold:
            result['is_everify'] = True
            result['employer_match_conf'] = round(best[1] / 100.0, 2)

    sh_names = [
        r[0] for r in
        db_session.query(SponsorHistory.normalized_name).distinct().all()
    ]
    if sh_names:
        best = process.extractOne(
            normalized, sh_names, scorer=fuzz.token_sort_ratio,
        )
        if best and best[1] >= confidence_threshold:
            sh_row = (
                db_session.query(SponsorHistory)
                .filter_by(normalized_name=best[0])
                .order_by(SponsorHistory.fiscal_year.desc())
                .first()
            )
            if sh_row:
                result['h1b_lca_count'] = sh_row.lca_count
                result['median_wage'] = sh_row.median_wage
                result['wage_level'] = sh_row.prevailing_wage_level
                conf = round(best[1] / 100.0, 2)
                if result['employer_match_conf'] is None or conf > result['employer_match_conf']:
                    result['employer_match_conf'] = conf

    return result


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
    """Load an H-1B LCA / employer data-hub CSV into sponsor_history."""
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
    parser.add_argument('--load-lca', metavar='CSV',
                        help='Path to H-1B LCA / employer data hub CSV')
    parser.add_argument('--clear', action='store_true',
                        help='Clear existing records in target table(s) before loading')
    args = parser.parse_args()

    if not args.load_everify and not args.load_lca:
        parser.print_help()
        sys.exit(1)

    from flask import Flask
    from backend.models import db, EVerifyEmployer, SponsorHistory
    from config.settings import Config

    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

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
            n = load_lca_csv(args.load_lca, db.session)
            print(f"Loaded {n} H-1B sponsor records")


if __name__ == '__main__':
    main()
