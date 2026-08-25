"""
LinkedIn Guest Jobs API Scraper
Scrapes public LinkedIn job listings without authentication.
Targets USA full-time / entry-level positions, sorted by date.
Server-side filter: past week. No client-side hard drop — freshness
is computed and stored for the UI to badge.
"""

from .base_scraper import BaseScraper
from datetime import datetime, timezone, timedelta
import urllib.parse
import re


class LinkedInScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "linkedin"
        self.base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def search_jobs(self, keyword: str, location: str = 'United States', page: int = 1) -> list:
        """Search LinkedIn for both full-time and internship/co-op listings."""
        if not location:
            location = 'United States'

        # Rotate job types: F=full-time, I=internship, ''=any (catches co-op)
        from config.settings import Config
        job_types = getattr(Config, 'LINKEDIN_JOB_TYPES', ['F', 'I', ''])

        seen_ids = set()
        jobs = []
        start = (page - 1) * 25

        for jt in job_types:
            params = {
                'keywords': keyword,
                'location': location,
                'f_TPR': 'r604800',       # Past week
                'f_E': '1,2',             # Entry + Associate
                'start': start,
                'sortBy': 'DD',
                'geoId': '103644278',
            }
            if jt:
                params['f_JT'] = jt

            url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
            soup = self.get_page(url)
            if not soup:
                continue

            for card in soup.find_all('div', class_='base-card'):
                try:
                    job_data = self.parse_job_listing(card)
                    if not job_data:
                        continue
                    eid = job_data.get('external_id') or job_data.get('job_url')
                    if eid and eid in seen_ids:
                        continue
                    if eid:
                        seen_ids.add(eid)
                    # Tag internship searches
                    if jt == 'I' and not job_data.get('job_type'):
                        job_data['job_type'] = 'internship'
                    jobs.append(job_data)
                except Exception as e:
                    print(f"Error parsing LinkedIn job: {e}")
                    continue

        if jobs:
            print(f"LinkedIn: Found {len(jobs)} jobs for '{keyword}' in '{location}'")

        return jobs

    def parse_job_listing(self, listing) -> dict:
        title_elem = listing.find('h3', class_='base-search-card__title')
        company_elem = listing.find('h4', class_='base-search-card__subtitle')
        location_elem = listing.find('span', class_='job-search-card__location')
        link_elem = listing.find('a', class_='base-card__full-link')
        date_elem = listing.find('time', class_='job-search-card__listdate')
        if not date_elem:
            date_elem = listing.find('time', class_='job-search-card__listdate--new')

        if not title_elem or not company_elem:
            return None

        title = title_elem.get_text(strip=True)
        company = company_elem.get_text(strip=True)
        location = location_elem.get_text(strip=True) if location_elem else ''
        job_url = link_elem.get('href') if link_elem else ''

        date_posted = None
        if date_elem:
            date_str = date_elem.get('datetime') or date_elem.get_text(strip=True)
            try:
                if date_str:
                    if '-' in date_str:
                        date_posted = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        date_posted = self.parse_relative_date(date_str)
            except (ValueError, TypeError):
                date_posted = datetime.now(timezone.utc)

        external_id = ''
        if job_url:
            match = re.search(r'view/(\d+)', job_url)
            if match:
                external_id = match.group(1)

        is_remote = 'remote' in location.lower() or 'remote' in title.lower()

        return self.create_job_dict(
            title=title,
            company=company,
            location=location,
            job_url=job_url,
            date_posted=date_posted,
            external_id=external_id,
            is_remote=is_remote,
        )
