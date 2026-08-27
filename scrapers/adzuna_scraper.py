"""
Adzuna API scraper — free backbone (~1000 calls/month).

Runs US + IN country indexes with a hard per-run call budget
(MAX_ADZUNA_CALLS, default 20). Missing credentials → skip with warning.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime, timezone

from config.settings import Config
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class AdzunaScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = 'adzuna'
        self.app_id = getattr(Config, 'ADZUNA_APP_ID', '') or ''
        self.app_key = getattr(Config, 'ADZUNA_APP_KEY', '') or ''
        self.max_calls = int(getattr(Config, 'MAX_ADZUNA_CALLS', 20))
        self.calls_used = 0
        self.session.headers.update({'Accept': 'application/json'})

    def _has_credentials(self) -> bool:
        return bool(self.app_id and self.app_key)

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        """Single keyword/location/page fetch (counts as one API call)."""
        if not self._has_credentials():
            logger.warning(
                'Adzuna: missing ADZUNA_APP_ID / ADZUNA_APP_KEY — skipping'
            )
            return []

        if self.calls_used >= self.max_calls:
            logger.info(
                f'Adzuna: call budget exhausted ({self.calls_used}/{self.max_calls})'
            )
            return []

        country = 'us'
        # Allow "us:Boston, MA" or plain location; country chosen by scrape()
        market = 'US'
        where = location or ''
        if where.lower().startswith('in:'):
            country, where, market = 'in', where[3:].strip(), 'IN'
        elif where.lower().startswith('us:'):
            country, where, market = 'us', where[3:].strip(), 'US'

        return self._fetch_page(keyword or 'Data Engineer', where, country, market, page)

    def _fetch_page(self, what: str, where: str, country: str, market: str, page: int = 1) -> list:
        if self.calls_used >= self.max_calls:
            return []

        params = {
            'app_id': self.app_id,
            'app_key': self.app_key,
            'results_per_page': 50,
            'what': what,
            'max_days_old': 7,
            'sort_by': 'date',
        }
        if where:
            params['where'] = where

        url = (
            f'https://api.adzuna.com/v1/api/jobs/{country}/search/{page}'
            f'?{urllib.parse.urlencode(params)}'
        )
        try:
            time.sleep(0.35)
            resp = self.safe_get(url, timeout=30)
            self.calls_used += 1
            if resp.status_code != 200:
                logger.warning(f'Adzuna HTTP {resp.status_code} ({country}/{what}/{where})')
                return []
            results = resp.json().get('results') or []
            jobs = []
            for item in results:
                parsed = self.parse_job_listing(item, market=market)
                if parsed:
                    jobs.append(parsed)
            logger.info(
                f"Adzuna [{country}]: {len(jobs)} jobs for '{what}'"
                f"{f' in {where}' if where else ''} "
                f"(calls {self.calls_used}/{self.max_calls})"
            )
            return jobs
        except Exception as e:
            self.calls_used += 1
            logger.warning(f'Adzuna fetch error: {e}')
            return []

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        """Budgeted sweep over US + IN indexes. Stops at MAX_ADZUNA_CALLS."""
        if not self._has_credentials():
            logger.warning(
                'Adzuna: missing ADZUNA_APP_ID / ADZUNA_APP_KEY — skipping'
            )
            return []

        self.calls_used = 0
        keywords = keywords or (Config.SEARCH_KEYWORDS[:5])
        us_locs = getattr(Config, 'ADZUNA_LOCATIONS_US', ['Remote'])
        in_locs = getattr(Config, 'ADZUNA_LOCATIONS_IN', ['Bangalore', 'Remote'])

        all_jobs = []
        seen = set()

        plans = (
            [('us', 'US', loc) for loc in us_locs]
            + [('in', 'IN', loc) for loc in in_locs]
        )

        for what in keywords:
            for country, market, loc in plans:
                if self.calls_used >= self.max_calls:
                    logger.info(
                        f'Adzuna: stopped at budget '
                        f'{self.calls_used}/{self.max_calls} calls'
                    )
                    return all_jobs
                batch = self._fetch_page(what, loc, country, market, page=1)
                for j in batch:
                    key = (j.get('external_id') or j.get('job_url') or '').strip()
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    all_jobs.append(j)

        logger.info(
            f'Adzuna scrape done: {len(all_jobs)} jobs, '
            f'calls_used={self.calls_used}/{self.max_calls}'
        )
        return all_jobs

    def parse_job_listing(self, job_data: dict, market: str = 'US') -> dict:
        if not isinstance(job_data, dict):
            return None

        title = job_data.get('title') or ''
        if not title:
            return None

        company_data = job_data.get('company') or {}
        company = (
            company_data.get('display_name', '')
            if isinstance(company_data, dict) else str(company_data or '')
        )

        location_data = job_data.get('location') or {}
        location = ''
        if isinstance(location_data, dict):
            display = location_data.get('display_name') or ''
            area = location_data.get('area') or []
            if area and isinstance(area, list):
                # Prefer display_name; fall back to last 2 area parts
                location = display or ', '.join(str(a) for a in area[-2:])
            else:
                location = display

        job_url = job_data.get('redirect_url') or ''
        description = job_data.get('description') or ''
        # Adzuna returns truncated snippets — always flag partial
        description_partial = True
        if description and not description.rstrip().endswith('…'):
            # Still a snippet API field even when not ellipsized
            description_partial = True

        date_posted = None
        created = job_data.get('created')
        if created:
            try:
                date_posted = datetime.fromisoformat(str(created).replace('Z', '+00:00'))
            except (ValueError, TypeError):
                date_posted = None

        salary_predicted = bool(job_data.get('salary_is_predicted'))
        # Coerce "0"/"1" string flags some Adzuna payloads use
        if isinstance(job_data.get('salary_is_predicted'), str):
            salary_predicted = job_data.get('salary_is_predicted') in ('1', 'true', 'True')

        salary_min = job_data.get('salary_min')
        salary_max = job_data.get('salary_max')
        try:
            salary_min = int(salary_min) if salary_min is not None else None
            salary_max = int(salary_max) if salary_max is not None else None
        except (TypeError, ValueError):
            salary_min = salary_max = None

        # Do not treat predicted salary as real for ranking — still store but flag
        loc_l = (location or '').lower()
        title_l = title.lower()

        return self.create_job_dict(
            title=title,
            company=company or 'Unknown',
            location=location or '',
            description=description,
            job_url=job_url,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
            is_remote='remote' in title_l or 'remote' in loc_l,
            external_id=f"adzuna-{market.lower()}-{job_data.get('id', '')}",
            market=market,
            salary_predicted=salary_predicted,
            description_partial=description_partial,
        )
