"""
The Muse API Scraper
Free public API - no authentication required for basic access
https://www.themuse.com/developers/api/v2
Filtered to USA-based internships/entry-level positions
"""

from .base_scraper import BaseScraper
from datetime import datetime, timedelta, timezone
import urllib.parse
import time

US_LOCATION_KEYWORDS = [
    'united states', 'usa', 'u.s.', 'remote',
    'new york', 'california', 'texas', 'colorado', 'maine',
    'new jersey', 'utah', 'nevada', 'arizona', 'idaho',
    'montana', 'wyoming', 'new mexico', 'kansas', 'nebraska',
    'iowa', 'arkansas', 'oklahoma', 'missouri', 'kentucky',
    'tennessee', 'alabama', 'south carolina', 'north dakota',
    'south dakota', 'wisconsin', 'minnesota', 'indiana', 'ohio',
    'michigan', 'pennsylvania', 'vermont', 'new hampshire',
    'boston', 'chicago', 'seattle', 'san francisco', 'los angeles',
    'atlanta', 'miami', 'denver', 'austin', 'dallas', 'houston',
    'portland', 'flexible',
]

NON_US_KEYWORDS = [
    'london', 'uk', 'united kingdom', 'germany', 'berlin',
    'france', 'paris', 'india', 'bangalore', 'mumbai',
    'canada', 'toronto', 'vancouver', 'australia', 'sydney',
    'singapore', 'japan', 'tokyo', 'brazil', 'netherlands',
    'amsterdam', 'ireland', 'dublin', 'spain', 'barcelona',
]


class TheMuseScraper(BaseScraper):
    MAX_AGE_DAYS = 60

    def __init__(self):
        super().__init__()
        self.source_name = "themuse"
        self.api_url = "https://www.themuse.com/api/public/jobs"
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def _is_usa_location(self, location_str: str) -> bool:
        loc_lower = location_str.lower()
        if not loc_lower or loc_lower == 'see posting':
            return True
        for kw in NON_US_KEYWORDS:
            if kw in loc_lower:
                return False
        for kw in US_LOCATION_KEYWORDS:
            if kw in loc_lower:
                return True
        return False

    def _is_recent(self, date_posted) -> bool:
        if not date_posted:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_AGE_DAYS)
        if date_posted.tzinfo is None:
            date_posted = date_posted.replace(tzinfo=timezone.utc)
        return date_posted >= cutoff

    def _fetch_and_filter(self, params, keyword, all_jobs, counters):
        """Fetch one API page and filter results."""
        url = f"{self.api_url}?{urllib.parse.urlencode(params, doseq=True)}"
        response = self.session.get(url, timeout=30)
        if response.status_code != 200:
            return
        data = response.json()
        for job_data in data.get('results', []):
            parsed = self.parse_job_listing(job_data)
            if not parsed:
                continue
            if not self._is_usa_location(parsed.get('location', '')):
                counters['non_us'] += 1
                continue
            if not self._is_recent(parsed.get('date_posted')):
                counters['old'] += 1
                continue
            if keyword:
                keyword_words = keyword.lower().split()
                full_text = f"{parsed['title'].lower()} {(parsed.get('description') or '').lower()}"
                if not any(w in full_text for w in keyword_words if len(w) > 2):
                    continue
            all_jobs.append(parsed)
        time.sleep(0.3)

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        jobs = []

        try:
            categories = [
                'Data Science',
                'Data and Analytics',
                'Software Engineering',
                'IT'
            ]

            us_api_locations = [
                'New York, NY',
                'Boston, MA',
                'Chicago, IL',
                'San Francisco, CA',
                'Austin, TX',
                'Denver, CO',
                'Seattle, WA',
                'Flexible / Remote',
            ]

            all_jobs = []
            counters = {'non_us': 0, 'old': 0}

            for level in ['Internship', 'Entry Level']:
                cats = categories if level == 'Internship' else categories[:2]
                for us_loc in us_api_locations:
                    for category in cats:
                        params = {
                            'page': page - 1,
                            'descending': 'true',
                            'level': level,
                            'category': category,
                            'location': us_loc,
                        }
                        self._fetch_and_filter(params, keyword, all_jobs, counters)

            seen_urls = set()
            for job in all_jobs:
                if job['job_url'] not in seen_urls:
                    seen_urls.add(job['job_url'])
                    jobs.append(job)

            print(f"The Muse: Found {len(jobs)} USA jobs" +
                  (f" matching '{keyword}'" if keyword else "") +
                  f" (skipped {counters['non_us']} non-US, {counters['old']} old)")

        except Exception as e:
            print(f"Error fetching The Muse jobs: {e}")

        return jobs

    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None

        title = job_data.get('name', '')

        company_data = job_data.get('company', {})
        company = company_data.get('name', '') if isinstance(company_data, dict) else ''

        locations = job_data.get('locations', [])
        location_str = ''
        if locations:
            location_names = [loc.get('name', '') for loc in locations if isinstance(loc, dict)]
            location_str = ', '.join(filter(None, location_names))

        refs = job_data.get('refs', {})
        job_url = refs.get('landing_page', '') if isinstance(refs, dict) else ''

        description = job_data.get('contents', '')

        date_posted = None
        pub_date = job_data.get('publication_date')
        if pub_date:
            try:
                date_posted = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                date_posted = datetime.now(timezone.utc)

        is_remote = 'remote' in location_str.lower() or 'flexible' in location_str.lower()

        categories = job_data.get('categories', [])
        if categories:
            cat_names = [c.get('name', '') for c in categories if isinstance(c, dict)]
            if cat_names:
                description = f"{description}\n\nCategories: {', '.join(cat_names)}"

        levels = job_data.get('levels', [])
        if levels:
            level_names = [lv.get('name', '') for lv in levels if isinstance(lv, dict)]
            if level_names:
                description = f"{description}\nLevel: {', '.join(level_names)}"

        if not title or not company:
            return None

        return self.create_job_dict(
            title=title,
            company=company,
            location=location_str or 'See posting',
            description=description,
            job_url=job_url,
            date_posted=date_posted,
            is_remote=is_remote,
            external_id=str(job_data.get('id', ''))
        )
