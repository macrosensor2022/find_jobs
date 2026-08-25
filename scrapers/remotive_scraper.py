"""
Remotive API Scraper
Free API for remote jobs - filters to USA only
https://remotive.com/api
"""

from .base_scraper import BaseScraper
from datetime import datetime, timezone
import time
import logging

logger = logging.getLogger(__name__)


US_LOCATIONS = [
    'united states', 'usa', 'us', 'u.s.', 'u.s.a',
    'new york', 'california', 'texas', 'florida', 'massachusetts',
    'washington', 'illinois', 'ohio', 'michigan', 'colorado',
    'utah', 'wisconsin', 'maine', 'new jersey', 'connecticut',
    'boston', 'san francisco', 'los angeles', 'seattle', 'chicago',
    'austin', 'dallas', 'denver', 'portland', 'atlanta', 'miami',
    'remote', 'anywhere',
]

NON_US_INDICATORS = [
    'europe', 'uk', 'london', 'germany', 'berlin', 'france', 'paris',
    'canada', 'toronto', 'vancouver', 'australia', 'sydney',
    'india', 'singapore', 'japan', 'dubai',
]


class RemotiveScraper(BaseScraper):
    """Remotive API - free for remote jobs"""

    def __init__(self):
        super().__init__()
        self.source_name = "remotive"
        self.api_url = "https://remotive.com/api/remote-jobs"
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        """Search jobs using Remotive API"""
        jobs = []

        try:
            params = {
                'category': 'software-dev',
                'limit': 50,
            }

            if keyword:
                params['search'] = keyword

            response = self.safe_get(self.api_url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                all_jobs = data.get('jobs', [])

                for job in all_jobs:
                    parsed = self.parse_job_listing(job)
                    if not parsed:
                        continue

                    job_location = (parsed.get('location') or '').lower()
                    if not self._is_usa_compatible(job_location):
                        continue

                    jobs.append(parsed)

                logger.info(f"Remotive: Found {len(jobs)} USA jobs for '{keyword}'")
            else:
                logger.warning(f"Remotive API returned {response.status_code}")

        except Exception as e:
            logger.error(f"Remotive error: {str(e)}")

        return jobs

    def _is_usa_compatible(self, location: str) -> bool:
        """Check if location is USA or Remote. Worldwide only passes if no
        non-US indicators are present."""
        loc = (location or '').lower().strip()
        if not loc or loc in ('remote', 'anywhere'):
            return True

        for indicator in NON_US_INDICATORS:
            if indicator in loc:
                return False

        if loc in ('worldwide', 'global'):
            return True

        for indicator in US_LOCATIONS:
            if indicator in loc:
                return True

        return False

    def _parse_date(self, date_str: str) -> datetime:
        """Parse Remotive ISO date; default to now (UTC) when missing/invalid."""
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    def parse_job_listing(self, job_data: dict) -> dict:
        """Parse a single Remotive job listing into the shared job dict shape."""
        if not isinstance(job_data, dict):
            return None

        title = job_data.get('title', '')
        company = job_data.get('company_name', '')
        if not title or not company:
            return None

        location = job_data.get('candidate_required_location', 'Remote') or 'Remote'

        return self.create_job_dict(
            title=title,
            company=company,
            location=location,
            description=job_data.get('description', ''),
            job_url=job_data.get('url', ''),
            date_posted=self._parse_date(job_data.get('publication_date', '')),
            is_remote=True,
            external_id=str(job_data.get('id', '')),
        )

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        """Helper: scrape across multiple keywords and deduplicate."""
        all_jobs = []
        keywords = keywords or ['AI', 'Machine Learning', 'Data Science']

        for keyword in keywords:
            jobs = self.search_jobs(keyword=keyword)
            all_jobs.extend(jobs)
            time.sleep(0.5)

        seen = set()
        deduped = []
        for job in all_jobs:
            key = (job.get('external_id') or '').strip() or (job.get('job_url') or '').strip()
            if not key:
                key = f"{job.get('title', '')}|{job.get('company', '')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped
