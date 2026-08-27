"""
JSearch API scraper — freshness + India-board booster (use sparingly).

Free tier ~200 calls/month. Cap via MAX_JSEARCH_CALLS (default 8).
Host/URL swappable via JSEARCH_HOST / JSEARCH_BASE_URL for RapidAPI ↔ OpenWeb Ninja.
Missing JSEARCH_API_KEY → skip with warning.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from config.settings import Config
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class JSearchScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = 'jsearch'
        self.api_key = getattr(Config, 'JSEARCH_API_KEY', '') or ''
        self.host = getattr(Config, 'JSEARCH_HOST', 'jsearch.p.rapidapi.com')
        self.base_url = getattr(
            Config, 'JSEARCH_BASE_URL', 'https://jsearch.p.rapidapi.com/search'
        )
        self.max_calls = int(getattr(Config, 'MAX_JSEARCH_CALLS', 8))
        self.calls_used = 0

    def _has_credentials(self) -> bool:
        return bool(self.api_key)

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        if not self._has_credentials():
            logger.warning('JSearch: missing JSEARCH_API_KEY — skipping')
            return []
        if self.calls_used >= self.max_calls:
            logger.info(
                f'JSearch: call budget exhausted ({self.calls_used}/{self.max_calls})'
            )
            return []

        if keyword and location:
            query = f'{keyword} in {location}'
        else:
            query = keyword or 'Data Engineer in United States'
        return self._fetch(query)

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        """Spend budget only on Config.JSEARCH_QUERIES (core DE titles)."""
        if not self._has_credentials():
            logger.warning('JSearch: missing JSEARCH_API_KEY — skipping')
            return []

        self.calls_used = 0
        queries = list(getattr(Config, 'JSEARCH_QUERIES', []) or [])
        if not queries and keywords:
            # Fallback: a few role×location pairs
            locs = (locations or ['United States', 'India'])[:2]
            for kw in (keywords or [])[:2]:
                for loc in locs:
                    queries.append(f'{kw} in {loc}')

        all_jobs = []
        seen = set()
        for q in queries:
            if self.calls_used >= self.max_calls:
                break
            for j in self._fetch(q):
                key = (j.get('external_id') or j.get('job_url') or '').strip()
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                all_jobs.append(j)

        logger.info(
            f'JSearch scrape done: {len(all_jobs)} jobs, '
            f'calls_used={self.calls_used}/{self.max_calls}'
        )
        return all_jobs

    def _fetch(self, query: str) -> list:
        if self.calls_used >= self.max_calls:
            return []

        headers = {
            'X-RapidAPI-Key': self.api_key,
            'X-RapidAPI-Host': self.host,
            'Accept': 'application/json',
        }
        params = {
            'query': query,
            'page': '1',
            'num_pages': '1',
            'date_posted': 'week',
        }
        try:
            time.sleep(0.4)
            resp = self.safe_get(
                self.base_url, headers=headers, params=params, timeout=30,
            )
            self.calls_used += 1
            if resp.status_code != 200:
                logger.warning(f'JSearch HTTP {resp.status_code} for query={query!r}')
                return []
            data = resp.json()
            items = data.get('data') or []
            jobs = []
            for item in items:
                parsed = self.parse_job_listing(item)
                if parsed:
                    jobs.append(parsed)
            logger.info(
                f"JSearch: {len(jobs)} jobs for '{query}' "
                f"(calls {self.calls_used}/{self.max_calls})"
            )
            return jobs
        except Exception as e:
            self.calls_used += 1
            logger.warning(f'JSearch fetch error: {e}')
            return []

    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None

        title = job_data.get('job_title') or ''
        if not title:
            return None

        company = job_data.get('employer_name') or 'Unknown'
        city = job_data.get('job_city') or ''
        state = job_data.get('job_state') or ''
        country = (job_data.get('job_country') or '').upper()
        parts = [p for p in (city, state, country) if p]
        location = ', '.join(parts) if parts else country

        if country in ('IN', 'IND', 'INDIA'):
            market = 'IN'
        elif country in ('US', 'USA', 'UNITED STATES'):
            market = 'US'
        else:
            # Infer from query/location text
            loc_l = location.lower()
            market = 'IN' if any(
                x in loc_l for x in ('india', 'bangalore', 'bengaluru', 'hyderabad',
                                     'chennai', 'mumbai', 'pune', 'delhi')
            ) else 'US'

        # A Google search link is not an application page. Keep it so the job
        # is still discoverable, but label it so it can never be presented as
        # a verified "Apply Now" destination.
        apply_link = job_data.get('job_apply_link') or ''
        if apply_link:
            job_url, url_status = apply_link, 'unverified'
        elif job_data.get('job_google_link'):
            job_url, url_status = job_data['job_google_link'], 'search_fallback'
        else:
            job_url, url_status = '', 'unknown'
        description = job_data.get('job_description') or ''

        date_posted = None
        raw_dt = job_data.get('job_posted_at_datetime_utc')
        if raw_dt:
            try:
                date_posted = datetime.fromisoformat(str(raw_dt).replace('Z', '+00:00'))
            except (ValueError, TypeError):
                date_posted = None

        salary_min = job_data.get('job_min_salary')
        salary_max = job_data.get('job_max_salary')
        try:
            salary_min = int(salary_min) if salary_min is not None else None
            salary_max = int(salary_max) if salary_max is not None else None
        except (TypeError, ValueError):
            salary_min = salary_max = None

        eid = job_data.get('job_id') or ''
        return self.create_job_dict(
            title=title,
            company=company,
            location=location,
            description=description,
            job_url=job_url,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
            application_url_status=url_status,
            is_remote=bool(job_data.get('job_is_remote'))
                      or 'remote' in location.lower(),
            external_id=f'jsearch-{eid}' if eid else '',
            market=market,
            salary_predicted=False,
            description_partial=False,
        )

    def parse_job_listing_alias(self, listing) -> dict:
        return self.parse_job_listing(listing) if isinstance(listing, dict) else {}
