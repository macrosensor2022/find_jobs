"""
SimplifyJobs GitHub listing feeds (new-grad + internships).

Public JSON maintained by Simplify / Pitt CSC — no API key:
  - New-Grad-Positions/.github/scripts/listings.json
  - Summer2026 / Summer2027 Internships listings.json

Filtered to DE / Analytics / BI / data roles that fit the user profile,
TARGET_STATES (+ remote), and sponsorship when the feed provides it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from scrapers.base_scraper import BaseScraper
from config.settings import Config

logger = logging.getLogger(__name__)

# Core skill / role tokens (must appear in title for Software category)
SKILL_KEYWORDS = (
    'data engineer', 'analytics engineer', 'bi engineer', 'business intelligence',
    'etl', 'elt', 'ssis', 'sql server', 'data warehouse',
    'data analyst', 'power bi', 'azure data',
    'data scientist', 'machine learning', 'ml engineer', 'ai engineer',
    'nlp', 'applied scientist', 'data platform', 'analytics platform',
    'bi developer', 'informatica', 'snowflake', 'databricks',
    'spark', 'airflow', 'dbt', 'associate data', 'junior data',
    'data engineering', 'analytics engineering',
)

# Soft early-career markers (not enough alone)
EARLY_MARKERS = (
    'co-op', 'coop', 'intern', 'new grad', 'university grad',
    'early career', 'graduate',
)

PREFERRED_CATEGORIES = {
    'ai/ml/data',
    'data science, ai & machine learning',
    'data',
}

EXCLUDED_TITLE_MARKERS = (
    'senior', 'staff', 'principal', 'director', 'manager', 'lead ',
    'vp ', 'chief ', 'architect',
)


INTERNSHIP_TITLE_RE = re.compile(
    r'\b(intern(?:ship)?s?|co[\s\-]?ops?|coops?)\b',
    re.I,
)


def is_internship_role(title: str = '', job_type: str = '') -> bool:
    """True for internship / co-op titles or job_type."""
    jt = (job_type or '').lower()
    if jt in ('internship', 'intern', 'co-op', 'coop', 'co_op'):
        return True
    return bool(INTERNSHIP_TITLE_RE.search(title or ''))


class GithubSimplifyScraper(BaseScraper):
    """Fetches one or more SimplifyJobs listings.json feeds."""

    MAX_AGE_DAYS = 14  # keep the feed focused on currently open new-grad roles

    def __init__(self, feeds: List[dict] = None, source_name: str = 'github_newgrad'):
        super().__init__()
        self.source_name = source_name
        self.feeds = feeds or getattr(Config, 'GITHUB_SIMPLIFY_FEEDS', [])
        self.excluded_states = list(getattr(Config, 'EXCLUDED_STATES', []))
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'JobTracker/1.0 (personal job search; +https://github.com/macrosensor2022)',
        })

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        return self.scrape(keywords=[keyword] if keyword else None, locations=[location] if location else None)

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        all_jobs = []
        seen = set()
        for feed in self.feeds:
            # When registered as github_newgrad, only newgrad feeds;
            # github_intern only internship feeds. Source name "github_simplify" = all.
            feed_kind = (feed.get('kind') or '').lower()
            if self.source_name == 'github_newgrad' and feed_kind != 'newgrad':
                continue
            if self.source_name == 'github_intern' and feed_kind != 'intern':
                continue

            url = feed.get('url')
            if not url:
                continue
            batch = self._fetch_feed(url, default_job_type=feed.get('job_type', 'full-time'))
            for job in batch:
                key = (job.get('external_id') or job.get('job_url') or '').strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                all_jobs.append(job)

        logger.info(
            '%s: %d skill-matched jobs from %d feed(s)',
            self.source_name, len(all_jobs), len(self.feeds),
        )
        return all_jobs

    def _fetch_feed(self, url: str, default_job_type: str = 'full-time') -> list:
        try:
            resp = self.safe_get(url, timeout=45)
            if resp.status_code != 200:
                logger.warning('Simplify feed HTTP %s: %s', resp.status_code, url)
                return []
            data = resp.json()
        except Exception as e:
            logger.warning('Simplify feed error (%s): %s', url, e)
            return []

        if not isinstance(data, list):
            logger.warning('Simplify feed: unexpected JSON shape from %s', url)
            return []

        jobs = []
        for item in data:
            parsed = self.parse_job_listing(item, default_job_type=default_job_type)
            if parsed:
                jobs.append(parsed)
        return jobs

    def parse_job_listing(self, listing, default_job_type: str = 'full-time') -> Optional[dict]:
        if not listing or not isinstance(listing, dict):
            return None
        if listing.get('active') is False:
            return None
        if listing.get('is_visible') is False:
            return None

        title = (listing.get('title') or '').strip()
        company = (listing.get('company_name') or '').strip()
        if not title or not company:
            return None

        # Full-time new-grad feed: never keep intern / co-op titles
        if self.source_name == 'github_newgrad' and is_internship_role(title):
            return None

        if not self._title_matches_skills(title, listing.get('category')):
            return None

        locs = listing.get('locations') or []
        if isinstance(locs, str):
            locs = [locs]
        location = ', '.join(str(x) for x in locs if x) or 'Remote'
        if not self._location_ok(location):
            return None

        date_posted = self._parse_ts(listing.get('date_posted') or listing.get('date_updated'))
        if date_posted and not self._is_recent(date_posted):
            return None

        sponsorship = (listing.get('sponsorship') or '').strip()
        desc_parts = [
            f"Category: {listing.get('category') or 'n/a'}",
            f"Source list: SimplifyJobs GitHub",
        ]
        if sponsorship:
            desc_parts.append(f"Sponsorship note: {sponsorship}")
        degrees = listing.get('degrees') or []
        if degrees:
            desc_parts.append('Degrees: ' + ', '.join(degrees))
        terms = listing.get('terms') or []
        if terms:
            desc_parts.append('Terms: ' + ', '.join(terms))

        job_type = default_job_type
        title_l = title.lower()
        if any(x in title_l for x in ('intern', 'co-op', 'coop', 'co op')):
            job_type = 'internship'
        elif any(x in title_l for x in ('new grad', 'university grad', 'early career', 'graduate')):
            job_type = 'full-time'

        is_remote = bool(re.search(r'\bremote\b', location, re.I))

        job = self.create_job_dict(
            title=title,
            company=company,
            location=location,
            description='\n'.join(desc_parts),
            job_url=(listing.get('url') or '').strip(),
            job_type=job_type,
            date_posted=date_posted,
            is_remote=is_remote,
            external_id=str(listing.get('id') or listing.get('url') or ''),
            market='US',
            description_partial=True,
        )
        # Soft signal for OPT enrichment
        if sponsorship and 'does not offer sponsorship' in sponsorship.lower():
            job['sponsorship_hint'] = 'no_sponsorship'
        elif sponsorship and 'citizenship' in sponsorship.lower():
            job['sponsorship_hint'] = 'citizenship_required'
        return job

    def _title_matches_skills(self, title: str, category: str = None) -> bool:
        t = (title or '').lower()
        if any(m in t for m in EXCLUDED_TITLE_MARKERS):
            if not any(x in t for x in ('new grad', 'intern', 'university', 'associate', 'junior')):
                return False

        def _has(token: str) -> bool:
            # Word-boundary style so "ssis" does not match inside "assistant"
            return bool(re.search(rf'(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])', t))

        has_skill = any(_has(k) for k in SKILL_KEYWORDS)
        cat = (category or '').lower().strip()
        cat_is_data = (
            cat in PREFERRED_CATEGORIES
            or 'data' in cat
            or cat.startswith('ai')
            or 'ml' in cat
            or 'machine learning' in cat
        )

        if cat_is_data:
            # Data category: need a real role word, not just "data labeler"
            roleish = any(
                _has(x) if ' ' not in x else x in t
                for x in (
                    'engineer', 'analyst', 'scientist', 'developer',
                    'architect', 'associate',
                )
            ) or any(x in t for x in ('new grad', 'university grad', 'early career', 'bi '))
            soft = (
                'data' in t
                or 'analytics' in t
                or 'machine learning' in t
                or 'business intelligence' in t
                or _has('ml')
                or (' ai' in f' {t}')
                or t.startswith('ai ')
            )
            return has_skill or (soft and roleish)

        # Non-data categories (e.g. Software / Quant): require explicit skill keyword
        return has_skill

    def _location_ok(self, location: str) -> bool:
        loc = (location or '').lower()
        if not loc or 'remote' in loc or 'united states' in loc or loc in ('usa', 'us'):
            return True

        excluded = [
            s.upper() for s in (
                self.excluded_states
                if self.excluded_states is not None
                else getattr(Config, 'EXCLUDED_STATES', [])
            )
        ]

        # Portland ME is OK; Portland OR is not when OR is on the excluded list.
        if 'OR' in excluded and re.search(r'portland\s*,?\s*(or|oregon)\b', loc):
            return False

        for match in re.finditer(r',\s*([a-z]{2})\b', loc):
            code = match.group(1).upper()
            if code == 'DC':
                continue
            if code in excluded:
                if code == 'WA' and ('washington, dc' in loc or 'washington dc' in loc):
                    continue
                return False

        state_names = {
            'california': 'CA', 'oregon': 'OR', 'washington': 'WA',
        }
        for name, code in state_names.items():
            if name in loc and code in excluded:
                if code == 'WA' and ('dc' in loc or 'd.c' in loc):
                    continue
                return False

        # Prefer target metros / states (ranking hint only; not a hard drop)
        target_hints = (
            'maine', ', me', 'boston', 'massachusetts', ', ma',
            'texas', ', tx', 'dallas', 'austin', 'houston',
            'connecticut', ', ct', 'hartford',
            'new jersey', ', nj', 'newark',
            'new york', ', ny', 'nyc',
            'pennsylvania', ', pa', 'philadelphia', 'pittsburgh',
            'maryland', ', md', 'baltimore',
            'virginia', ', va', 'arlington', 'alexandria', 'reston',
            'washington, dc', 'washington dc', ', dc',
            'tennessee', ', tn', 'nashville',
            'north carolina', ', nc', 'charlotte',
            'ohio', ', oh', 'columbus',
            'minnesota', ', mn', 'minneapolis',
            'arizona', ', az', 'phoenix',
            'utah', ', ut', 'salt lake',
            'colorado', ', co', 'denver',
        )
        if any(h in loc for h in target_hints):
            return True

        # UK / EU / India only boards — drop unless also remote US
        foreign = (
            'london', 'uk', 'united kingdom', 'canada', 'toronto', 'india',
            'bangalore', 'bengaluru', 'hyderabad', 'germany', 'berlin',
            'france', 'paris', 'singapore', 'australia',
        )
        if any(f in loc for f in foreign) and 'remote' not in loc and 'united states' not in loc:
            return False

        return True

    def _parse_ts(self, value) -> Optional[datetime]:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                # Heuristic: ms vs s
                ts = float(value)
                if ts > 1e12:
                    ts /= 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            if isinstance(value, str) and value.isdigit():
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
        return None

    def _is_recent(self, date_posted: datetime) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_AGE_DAYS)
        if date_posted.tzinfo is None:
            date_posted = date_posted.replace(tzinfo=timezone.utc)
        return date_posted >= cutoff


class GithubNewGradScraper(GithubSimplifyScraper):
    def __init__(self):
        super().__init__(source_name='github_newgrad')


class GithubInternScraper(GithubSimplifyScraper):
    def __init__(self):
        super().__init__(source_name='github_intern')
