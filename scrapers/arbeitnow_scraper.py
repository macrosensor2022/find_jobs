"""
Arbeitnow API Scraper
Free API for tech/remote jobs - no key required
Filtered to USA-based positions only
"""

from .base_scraper import BaseScraper
from datetime import datetime, timedelta, timezone
import time


NON_US_INDICATORS = [
    'germany', 'berlin', 'munich', 'frankfurt', 'hamburg', 'stuttgart',
    'grünwald', 'grunwald', 'düsseldorf', 'dusseldorf', 'köln', 'koln',
    'uk', 'united kingdom', 'london', 'manchester', 'england', 'scotland',
    'france', 'paris', 'lyon', 'india', 'bangalore', 'mumbai', 'delhi', 'hyderabad', 'pune',
    'canada', 'toronto', 'vancouver', 'montreal', 'ottawa',
    'netherlands', 'amsterdam', 'rotterdam', 'spain', 'barcelona', 'madrid',
    'italy', 'milan', 'rome', 'australia', 'sydney', 'melbourne',
    'singapore', 'japan', 'tokyo', 'brazil', 'são paulo',
    'sweden', 'stockholm', 'switzerland', 'zurich', 'geneva',
    'ireland', 'dublin', 'portugal', 'lisbon', 'poland', 'warsaw', 'krakow',
    'austria', 'vienna', 'belgium', 'brussels', 'denmark', 'copenhagen',
    'norway', 'oslo', 'finland', 'helsinki', 'czech', 'prague',
    'china', 'beijing', 'shanghai', 'south korea', 'seoul',
    'mexico', 'argentina', 'buenos aires', 'colombia', 'bogota',
    'philippines', 'manila', 'indonesia', 'jakarta', 'vietnam',
    'israel', 'tel aviv', 'turkey', 'istanbul', 'nigeria', 'lagos',
    'europe', 'apac', 'emea', 'latam', 'asia',
]

US_LOCATION_INDICATORS = [
    'united states', 'usa', 'u.s.', 'u.s.a',
    'new york', 'ny', 'nyc', 'california', 'ca', 'san francisco', 'los angeles',
    'texas', 'tx', 'austin', 'dallas', 'houston', 'colorado', 'co', 'denver',
    'maine', 'me', 'portland, me', 'new jersey', 'nj', 'utah', 'ut',
    'nevada', 'nv', 'arizona', 'az', 'phoenix',
    'idaho', 'montana', 'wyoming', 'new mexico', 'kansas', 'nebraska',
    'iowa', 'arkansas', 'oklahoma', 'missouri', 'kentucky', 'tennessee',
    'alabama', 'south carolina', 'north dakota', 'south dakota',
    'wisconsin', 'minnesota', 'indiana', 'ohio', 'michigan',
    'pennsylvania', 'vermont', 'new hampshire',
    'seattle', 'wa', 'chicago', 'il', 'boston', 'ma',
    'atlanta', 'ga', 'miami', 'fl', 'virginia', 'va',
    'remote', 'anywhere',
]


class ArbeitnowScraper(BaseScraper):
    MAX_AGE_DAYS = 3

    def __init__(self):
        super().__init__()
        self.source_name = "arbeitnow"
        self.api_url = "https://www.arbeitnow.com/api/job-board-api"

    def _is_recent(self, created_at) -> bool:
        if not created_at:
            return False
        try:
            posted = datetime.fromtimestamp(created_at, tz=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_AGE_DAYS)
            return posted >= cutoff
        except (ValueError, TypeError, OSError):
            return False

    def _is_usa_job(self, location: str, title: str = '', description: str = '') -> bool:
        """Strict USA filter. Since Arbeitnow is primarily European,
        require explicit US location match and reject anything with non-US signals."""
        loc_lower = location.lower().strip()
        title_lower = title.lower()
        if not loc_lower:
            return False
        for indicator in NON_US_INDICATORS:
            if indicator in loc_lower:
                return False

        german_title_words = [
            'praktikum', 'werkstudent', 'ausbildung', 'personalsach',
            'sachbearbeiter', 'mitarbeiter', 'berater', 'leiter',
            'weiterbildung', 'projektassistenz', 'koordinator',
        ]
        for word in german_title_words:
            if word in title_lower:
                return False

        us_explicit = [
            'united states', 'usa', 'u.s.',
            'new york', 'california', 'texas', 'colorado', 'maine',
            'new jersey', 'utah', 'nevada', 'arizona',
            'san francisco', 'los angeles', 'chicago', 'boston', 'seattle',
            'atlanta', 'miami', 'denver', 'austin', 'dallas', 'houston',
        ]
        for indicator in us_explicit:
            if indicator in loc_lower:
                return True

        if loc_lower in ('remote', 'anywhere', 'worldwide'):
            return True

        return False

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        jobs = []

        try:
            time.sleep(1)
            response = self.session.get(self.api_url, timeout=30)
            response.raise_for_status()

            data = response.json()
            all_jobs = data.get('data', [])
            skipped_non_us = 0
            skipped_old = 0

            for job in all_jobs:
                if not self._is_recent(job.get('created_at')):
                    skipped_old += 1
                    continue

                job_location = job.get('location', '')
                job_title = job.get('title', '')
                job_desc = job.get('description', '')
                if not self._is_usa_job(job_location, job_title, job_desc):
                    skipped_non_us += 1
                    continue

                if keyword:
                    title = (job.get('title') or '').lower()
                    desc = (job.get('description') or '').lower()
                    tags = ' '.join(job.get('tags', [])).lower()
                    full_text = f"{title} {desc} {tags}"

                    keyword_words = keyword.lower().split()
                    if not any(word in full_text for word in keyword_words if len(word) > 2):
                        continue

                parsed = self.parse_job_listing(job)
                if parsed:
                    jobs.append(parsed)

            print(f"Arbeitnow: Found {len(jobs)} recent USA jobs" +
                  (f" matching '{keyword}'" if keyword else "") +
                  f" (skipped {skipped_old} old, {skipped_non_us} non-US)")

        except Exception as e:
            print(f"Arbeitnow error: {e}")

        return jobs

    def parse_job_listing(self, job: dict) -> dict:
        date_posted = None
        created_at = job.get('created_at')
        if created_at:
            try:
                date_posted = datetime.fromtimestamp(created_at)
            except (ValueError, TypeError, OSError):
                pass

        return self.create_job_dict(
            title=job.get('title', ''),
            company=job.get('company_name', ''),
            location=job.get('location', 'Remote'),
            description=job.get('description', ''),
            job_url=job.get('url', ''),
            date_posted=date_posted,
            is_remote=job.get('remote', False),
            external_id=str(job.get('slug', ''))
        )
