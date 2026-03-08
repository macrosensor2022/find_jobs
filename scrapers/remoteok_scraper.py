"""
RemoteOK API Scraper
Free JSON API - no authentication required
https://remoteok.com/api
Filtered to recent postings (last 14 days) relevant to USA
"""

from .base_scraper import BaseScraper
from datetime import datetime, timedelta, timezone
import time

NON_US_LOCATIONS = [
    'germany', 'berlin', 'munich', 'frankfurt', 'hamburg', 'stuttgart',
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
    'grünwald', 'grunwald', 'slovakia', 'bratislava',
    'romania', 'bucharest', 'bulgaria', 'sofia', 'croatia', 'zagreb',
    'hungary', 'budapest', 'serbia', 'belgrade', 'ukraine', 'kyiv',
    'lithuania', 'vilnius', 'latvia', 'riga', 'estonia', 'tallinn',
    'greece', 'athens', 'new zealand', 'auckland', 'south africa', 'cape town',
    'kenya', 'nairobi', 'egypt', 'cairo', 'morocco',
    'thailand', 'bangkok', 'malaysia', 'kuala lumpur', 'taiwan', 'taipei',
    'pakistan', 'karachi', 'bangladesh', 'dhaka', 'sri lanka', 'nepal',
]

US_INDICATORS = [
    'united states', 'usa', 'u.s.', 'us ',
    'new york', 'california', 'texas', 'colorado', 'maine',
    'new jersey', 'utah', 'nevada', 'arizona',
    'san francisco', 'los angeles', 'chicago', 'boston', 'seattle',
    'atlanta', 'miami', 'denver', 'austin', 'dallas', 'houston',
    'portland, me', 'portland, or',
]


class RemoteOKScraper(BaseScraper):
    MAX_AGE_DAYS = 14

    def __init__(self):
        super().__init__()
        self.source_name = "remoteok"
        self.api_url = "https://remoteok.com/api"
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def _is_recent(self, date_posted) -> bool:
        if not date_posted:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_AGE_DAYS)
        if date_posted.tzinfo is None:
            date_posted = date_posted.replace(tzinfo=timezone.utc)
        return date_posted >= cutoff

    def _is_usa_compatible(self, location: str) -> bool:
        """Accept if location is empty, Remote, Worldwide, or US-based. Reject non-US."""
        loc_lower = location.lower().strip()
        if not loc_lower or loc_lower in ('remote', 'worldwide', 'anywhere', 'global'):
            return True
        for indicator in NON_US_LOCATIONS:
            if indicator in loc_lower:
                return False
        for indicator in US_INDICATORS:
            if indicator in loc_lower:
                return True
        # If location doesn't match any known pattern, allow it (may be remote)
        return True

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        jobs = []

        try:
            time.sleep(1)

            response = self.session.get(self.api_url, timeout=30)
            response.raise_for_status()

            data = response.json()
            job_listings = data[1:] if len(data) > 1 else data
            skipped_old = 0
            skipped_region = 0

            for job_data in job_listings:
                parsed = self.parse_job_listing(job_data)
                if not parsed:
                    continue

                if not self._is_recent(parsed.get('date_posted')):
                    skipped_old += 1
                    continue

                if not self._is_usa_compatible(parsed.get('location', '')):
                    skipped_region += 1
                    continue

                if keyword:
                    title_lower = parsed['title'].lower()
                    desc_lower = (parsed.get('description') or '').lower()
                    tags = ' '.join(job_data.get('tags', [])).lower()
                    full_text = f"{title_lower} {desc_lower} {tags}"

                    keyword_words = keyword.lower().split()
                    if not any(word in full_text for word in keyword_words if len(word) > 2):
                        continue

                jobs.append(parsed)

            print(f"RemoteOK: Found {len(jobs)} recent USA-compatible jobs" +
                  (f" matching '{keyword}'" if keyword else "") +
                  f" (skipped {skipped_old} old, {skipped_region} non-US)")

        except Exception as e:
            print(f"Error fetching RemoteOK jobs: {e}")

        return jobs

    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None

        if 'position' not in job_data and 'title' not in job_data:
            return None

        title = job_data.get('position') or job_data.get('title', '')
        company = job_data.get('company', '')
        location = job_data.get('location', 'Remote')

        slug = job_data.get('slug', '')
        job_url = f"https://remoteok.com/remote-jobs/{slug}" if slug else job_data.get('url', '')

        date_posted = None
        if job_data.get('date'):
            try:
                date_str = job_data['date']
                date_posted = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                date_posted = datetime.now(timezone.utc)

        description = job_data.get('description', '')

        salary_min = job_data.get('salary_min')
        salary_max = job_data.get('salary_max')

        tags = job_data.get('tags', [])
        if tags:
            description = f"{description}\n\nTags: {', '.join(tags)}"

        if not title or not company:
            return None

        return self.create_job_dict(
            title=title,
            company=company,
            location=location,
            description=description,
            job_url=job_url,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
            is_remote=True,
            external_id=str(job_data.get('id', ''))
        )
