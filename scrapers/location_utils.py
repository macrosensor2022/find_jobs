"""
Location parsing, TARGET_STATES filtering, and Census CBSA crosswalk.

Uses Census Bureau List 2 (principal cities) July 2023 — not a hand-written metro dict.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# FIPS state code → USPS abbrev (Census list2 uses FIPS)
_FIPS_TO_STATE = {
    '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO',
    '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL', '13': 'GA', '15': 'HI',
    '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY',
    '22': 'LA', '23': 'ME', '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN',
    '28': 'MS', '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH',
    '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI', '45': 'SC', '46': 'SD',
    '47': 'TN', '48': 'TX', '49': 'UT', '50': 'VT', '51': 'VA', '53': 'WA',
    '54': 'WV', '55': 'WI', '56': 'WY', '72': 'PR',
}

_STATE_NAME_TO_ABBREV = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'district of columbia': 'DC', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI',
    'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
    'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME',
    'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE',
    'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM',
    'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
    'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI',
    'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
    'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
}

_ABBREV_TO_NAME = {v: k.title() for k, v in _STATE_NAME_TO_ABBREV.items()}

_REMOTE_RE = re.compile(
    r'\b(remote|work\s*from\s*home|wfh|anywhere|worldwide|global|flexible)\b',
    re.I,
)
_US_REMOTE_RE = re.compile(
    r'\b(remote[\s\-_]*(us|usa|united\s*states)|us[\s\-_]*remote|'
    r'united\s*states|usa|u\.s\.a?)\b',
    re.I,
)

# Module-level crosswalk cache: (city_lower, state_abbrev) -> (cbsa_code, cbsa_title)
_CROSSWALK: Dict[Tuple[str, str], Tuple[str, str]] = {}
_CROSSWALK_BY_CITY: Dict[str, List[Tuple[str, str, str]]] = {}  # city -> [(state, code, title)]
_LOADED_PATH: Optional[str] = None

# In-memory unparsed bucket (also persisted via record_unparsed)
_UNPARSED: Dict[str, int] = defaultdict(int)


def default_crosswalk_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, 'data', 'list2_2023.xlsx')


def load_cbsa_crosswalk(path: str = None, force: bool = False) -> int:
    """Load Census List 2 principal-cities file into memory. Returns row count."""
    global _CROSSWALK, _CROSSWALK_BY_CITY, _LOADED_PATH
    path = path or default_crosswalk_path()
    if _CROSSWALK and _LOADED_PATH == path and not force:
        return len(_CROSSWALK)

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Census CBSA crosswalk not found at {path}. "
            "Download list2_2023.xlsx from Census delineation files."
        )

    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    crosswalk: Dict[Tuple[str, str], Tuple[str, str]] = {}
    by_city: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 3:
            continue
        if not row or not row[0] or not row[3]:
            continue
        cbsa_code = str(row[0]).strip()
        cbsa_title = str(row[1]).strip()
        city = str(row[3]).strip()
        fips = str(row[4]).strip().zfill(2) if row[4] is not None else ''
        state = _FIPS_TO_STATE.get(fips)
        if not state or not city:
            continue
        key = (city.lower(), state)
        crosswalk[key] = (cbsa_code, cbsa_title)
        by_city[city.lower()].append((state, cbsa_code, cbsa_title))

        # Also index hyphenated CBSA title components as aliases for this state
        # e.g. "Dallas-Fort Worth-Arlington, TX" → dallas, fort worth, arlington
        title_cities = cbsa_title.split(',')[0]
        for part in re.split(r'[-/]', title_cities):
            part = part.strip().lower()
            if part and part != city.lower():
                alias_key = (part, state)
                if alias_key not in crosswalk:
                    crosswalk[alias_key] = (cbsa_code, cbsa_title)
                    by_city[part].append((state, cbsa_code, cbsa_title))

    wb.close()
    _CROSSWALK = crosswalk
    _CROSSWALK_BY_CITY = dict(by_city)
    _LOADED_PATH = path
    logger.info(f"Loaded CBSA crosswalk: {len(crosswalk)} city/state keys from {path}")
    return len(crosswalk)


def normalize_state(token: str) -> Optional[str]:
    if not token:
        return None
    t = token.strip().lower().replace('.', '')
    if len(t) == 2 and t.upper() in _ABBREV_TO_NAME:
        return t.upper()
    return _STATE_NAME_TO_ABBREV.get(t)


def _looks_remote(text: str) -> bool:
    return bool(_REMOTE_RE.search(text or ''))


def _is_us_remote(text: str) -> bool:
    if not text:
        return False
    if _US_REMOTE_RE.search(text):
        return True
    # Bare "Remote" / "Flexible / Remote" with no foreign country → treat as Remote-US
    if _looks_remote(text):
        foreign = ('uk', 'europe', 'india', 'canada', 'latam', 'emea', 'apac',
                   'germany', 'london', 'toronto', 'mexico', 'brazil')
        low = text.lower()
        if not any(f in low for f in foreign):
            return True
    return False


def canonicalize_location(raw: str) -> Dict:
    """Parse a messy job location into structured fields.

    CRITICAL: bare "Portland" → Portland, ME unless OR/Oregon is explicit.

    Returns dict:
      city, state, metro, metro_code, is_remote_us, parse_ok, raw
    """
    result = {
        'city': None,
        'state': None,
        'metro': None,
        'metro_code': None,
        'is_remote_us': False,
        'parse_ok': False,
        'raw': raw or '',
    }
    text = (raw or '').strip()
    if not text:
        record_unparsed(text or '(empty)')
        return result

    if _is_us_remote(text) and not re.search(
        r',\s*[A-Z]{2}\b|[A-Za-z]+,\s*(ME|TX|CT|NJ|MA|TN|NC|OH|MN|AZ|UT|CO|OR|CA|WA)\b',
        text, re.I,
    ):
        # Pure remote / flexible with no city — keep as Remote-US
        if not re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*[A-Z]{2}\b', text):
            result['is_remote_us'] = True
            result['state'] = 'REMOTE'
            result['metro'] = 'Remote-US'
            result['metro_code'] = 'REMOTE'
            result['parse_ok'] = True
            return result

    # Split multi-city Themuse strings on / or ; or |
    chunks = re.split(r'[;/|]|,\s*(?=[A-Z][a-z]+\s*,)', text)
    if len(chunks) == 1:
        chunks = [p.strip() for p in text.split(',') if p.strip()]
        # "Austin, TX, Bloomington, MN" style — pair city,state
        candidates = []
        i = 0
        parts = [p.strip() for p in text.split(',')]
        while i < len(parts):
            if i + 1 < len(parts) and normalize_state(parts[i + 1].split()[0] if parts[i + 1] else ''):
                candidates.append(f"{parts[i]}, {parts[i+1].split()[0]}")
                i += 2
            else:
                candidates.append(parts[i])
                i += 1
        chunks = candidates or [text]

    parsed = None
    for chunk in chunks:
        parsed = _parse_single_place(chunk.strip()) or parsed
        if parsed and parsed.get('state') and parsed.get('city'):
            break

    if not parsed:
        # Last resort: extract any state abbrev and city word before it
        m = re.search(
            r'([A-Za-z][A-Za-z\.\s\-]+?)\s*,?\s*\b('
            + '|'.join(_ABBREV_TO_NAME.keys())
            + r')\b',
            text, re.I,
        )
        if m:
            parsed = {
                'city': m.group(1).strip(' ,'),
                'state': normalize_state(m.group(2)),
            }

    if not parsed or not parsed.get('state'):
        if _is_us_remote(text):
            result['is_remote_us'] = True
            result['state'] = 'REMOTE'
            result['metro'] = 'Remote-US'
            result['metro_code'] = 'REMOTE'
            result['parse_ok'] = True
            return result
        record_unparsed(text)
        return result

    city = parsed['city']
    state = parsed['state']

    # Portland rule
    if city and city.lower() == 'portland':
        low = text.lower()
        if re.search(r'\b(or|oregon)\b', low) and not re.search(r'\b(me|maine)\b', low):
            state = 'OR'
        else:
            state = 'ME'

    result['city'] = city
    result['state'] = state

    if not _CROSSWALK:
        try:
            load_cbsa_crosswalk()
        except FileNotFoundError as e:
            logger.warning(str(e))

    metro_hit = lookup_metro(city, state)
    if metro_hit:
        result['metro_code'], result['metro'] = metro_hit
        result['parse_ok'] = True
    else:
        # State-only parse still useful for TARGET_STATES filter
        result['parse_ok'] = True
        result['metro'] = f"{city}, {state}" if city else state
        result['metro_code'] = None

    if _looks_remote(text):
        result['is_remote_us'] = result['is_remote_us'] or _is_us_remote(text)

    return result


def _parse_single_place(chunk: str) -> Optional[Dict]:
    if not chunk:
        return None
    chunk = re.sub(r'\(.*?\)', '', chunk).strip()
    # "City, ST" or "City, State"
    m = re.match(
        r'^([A-Za-z][A-Za-z\.\s\-\']+?)\s*,\s*([A-Za-z\.]{2,}|'
        + '|'.join(_STATE_NAME_TO_ABBREV.keys())
        + r')\b',
        chunk, re.I,
    )
    if m:
        st = normalize_state(m.group(2))
        if st:
            return {'city': m.group(1).strip(), 'state': st}

    # "City ST"
    m = re.match(r'^([A-Za-z][A-Za-z\.\s\-\']+?)\s+([A-Z]{2})$', chunk.strip())
    if m and normalize_state(m.group(2)):
        return {'city': m.group(1).strip(), 'state': m.group(2).upper()}

    # Bare city with optional state elsewhere handled by Portland rule
    if re.match(r'^[A-Za-z][A-Za-z\.\s\-\']+$', chunk) and len(chunk) < 40:
        city = chunk.strip()
        st = None
        if city.lower() == 'portland':
            st = 'ME'
        return {'city': city, 'state': st}

    return None


def lookup_metro(city: str, state: str) -> Optional[Tuple[str, str]]:
    """Return (cbsa_code, cbsa_title) from Census crosswalk."""
    if not city or not state:
        return None
    if not _CROSSWALK:
        try:
            load_cbsa_crosswalk()
        except FileNotFoundError:
            return None
    key = (city.lower().strip(), state.upper())
    if key in _CROSSWALK:
        return _CROSSWALK[key]
    # Strip "Saint" / "St."
    alt = city.lower().replace('saint ', 'st. ').replace('st ', 'st. ')
    key2 = (alt, state.upper())
    if key2 in _CROSSWALK:
        return _CROSSWALK[key2]
    return None


def in_target_states(state: str, target_states: List[str], allow_remote: bool = True) -> bool:
    if not state:
        return False
    st = state.upper()
    if st in ('REMOTE', 'US', 'USA') and allow_remote:
        return True
    excluded = {'CA', 'WA', 'OR'}
    if st in excluded:
        return False
    return st in {s.upper() for s in target_states}


def record_unparsed(raw: str):
    key = (raw or '').strip()[:255] or '(empty)'
    _UNPARSED[key] += 1


def get_unparsed_bucket(limit: int = 50) -> List[Dict]:
    items = sorted(_UNPARSED.items(), key=lambda x: -x[1])[:limit]
    return [{'location': k, 'count': v} for k, v in items]


def unparsed_stats() -> Dict:
    total = sum(_UNPARSED.values())
    return {
        'unique_unparsed': len(_UNPARSED),
        'total_unparsed_hits': total,
        'top': get_unparsed_bucket(20),
    }


def persist_unparsed(db_session):
    """Flush in-memory unparsed bucket into UnparsedLocation table."""
    from backend.models import UnparsedLocation
    for loc, count in _UNPARSED.items():
        row = db_session.query(UnparsedLocation).filter_by(location=loc).first()
        if row:
            row.hit_count = (row.hit_count or 0) + count
        else:
            db_session.add(UnparsedLocation(location=loc, hit_count=count))
    db_session.commit()
    _UNPARSED.clear()
