"""Location preference scoring driven by user-editable preferences."""

import re

from config.settings import Config
from services.text_utils import normalize

_REMOTE_RE = re.compile(r'\b(remote|work from home|wfh|distributed|anywhere)\b', re.I)
_HYBRID_RE = re.compile(r'\bhybrid\b', re.I)
_ONSITE_RE = re.compile(r'\b(on[\s\-]?site|in[\s\-]?office|in[\s\-]?person)\b', re.I)
_RELOCATION_RE = re.compile(r'\brelocation\s+(assistance|support|package|provided|offered)\b', re.I)
_NON_US_RE = re.compile(
    r'\b(india|canada|united kingdom|uk|london|germany|ireland|dublin|'
    r'singapore|australia|japan|china|brazil|mexico|poland|netherlands|'
    r'bangalore|bengaluru|hyderabad|pune|chennai|mumbai|noida|gurgaon|toronto|'
    r'vancouver|emea|apac)\b', re.I,
)


def detect_remote_type(location, description=''):
    """remote | hybrid | onsite | unknown, based on stated text only."""
    text = f'{location or ""} {normalize(description)[:2000]}'
    if _HYBRID_RE.search(text):
        return 'hybrid'
    if _REMOTE_RE.search(location or ''):
        return 'remote'
    if _REMOTE_RE.search(text) and not _ONSITE_RE.search(text):
        return 'remote'
    if _ONSITE_RE.search(text):
        return 'onsite'
    return 'unknown'


def get_preferences(overrides=None):
    """Merge stored preference overrides on top of the config defaults."""
    prefs = {
        'preferred_states': list(Config.PREFERRED_STATES),
        'acceptable_states': list(Config.ACCEPTABLE_STATES),
        'allow_remote_us': Config.ALLOW_REMOTE_US,
        'allow_hybrid': Config.ALLOW_HYBRID,
        'allow_relocation': Config.ALLOW_RELOCATION,
        'excluded_states': list(getattr(Config, 'EXCLUDED_STATES', [])),
    }
    if overrides:
        for key, value in overrides.items():
            if key in prefs and value is not None:
                prefs[key] = value
    return prefs


def score_location(location, description='', state=None, is_remote=None,
                   preferences=None):
    """Score the location dimension 0-100 with a stated reason."""
    prefs = get_preferences(preferences)
    loc_text = location or ''
    remote_type = detect_remote_type(loc_text, description)
    if is_remote and remote_type == 'unknown':
        remote_type = 'remote'

    reasons, risks = [], []

    if not loc_text.strip() and remote_type == 'unknown':
        return {
            'score': 50.0, 'remote_type': 'unknown', 'state': state,
            'reasons': [], 'risks': ['Location not stated in the posting'],
        }

    non_us = _NON_US_RE.search(loc_text)
    if non_us and remote_type != 'remote':
        return {
            'score': 5.0, 'remote_type': remote_type, 'state': state,
            'reasons': [],
            'risks': [f'Located outside the US ({non_us.group(0)})'],
        }

    state_u = (state or '').upper()
    if state_u in [s.upper() for s in prefs['excluded_states']]:
        return {
            'score': 15.0, 'remote_type': remote_type, 'state': state_u,
            'reasons': [], 'risks': [f'{state_u} is on your excluded-states list'],
        }

    score = None
    if state_u and state_u in [s.upper() for s in prefs['preferred_states']]:
        score = 100.0
        reasons.append(f'{state_u} is a preferred state')
    elif state_u in ('REMOTE',) or remote_type == 'remote':
        if prefs['allow_remote_us']:
            score = 92.0
            reasons.append('Remote (US)')
        else:
            score = 40.0
            risks.append('Remote role, but remote is disabled in your preferences')
    elif state_u and state_u in [s.upper() for s in prefs['acceptable_states']]:
        score = 70.0
        reasons.append(f'{state_u} is an acceptable state')
    elif state_u:
        score = 40.0
        risks.append(f'{state_u} is outside your preferred states')
    else:
        score = 50.0
        risks.append('Could not determine the state from the location text')

    if remote_type == 'hybrid':
        if prefs['allow_hybrid']:
            reasons.append('Hybrid schedule')
        else:
            score = min(score, 45.0)
            risks.append('Hybrid role, but hybrid is disabled in your preferences')

    if prefs['allow_relocation'] and _RELOCATION_RE.search(normalize(description)):
        score = min(100.0, score + 8.0)
        reasons.append('Relocation assistance mentioned')

    return {
        'score': round(score, 1),
        'remote_type': remote_type,
        'state': state_u or None,
        'reasons': reasons,
        'risks': risks,
    }
