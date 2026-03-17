"""
LinkedIn Guest Jobs API Scraper
Scrapes public LinkedIn job listings without authentication
Targets USA internships/entry-level positions, sorted by date
Defaults to last 24 hours to surface the freshest postings
"""

from .base_scraper import BaseScraper
from datetime import datetime, timedelta, timezone
import urllib.parse
import re


class LinkedInScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "linkedin"
        self.base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def search_jobs(self, keyword: str, location: str = 'United States', page: int = 1) -> list:
        jobs = []
        start = (page - 1) * 25

        if not location:
            location = 'United States'

        params = {
            'keywords': keyword,
            'location': location,
            'f_TPR': 'r86400',        # Past 24 hours (was r604800 = past week)
            'f_E': '1',               # Entry level
            'f_JT': 'I',              # Internship job type
            'start': start,
            'sortBy': 'DD',           # Sort by date
            'geoId': '103644278',     # United States geoId
        }

        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"

        soup = self.get_page(url)
        if not soup:
            return jobs

        job_cards = soup.find_all('div', class_='base-card')
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        skipped_old = 0

        for card in job_cards:
            try:
                job_data = self.parse_job_listing(card)
                if not job_data:
                    continue
                dp = job_data.get('date_posted')
                if dp:
                    if dp.tzinfo is None:
                        dp = dp.replace(tzinfo=timezone.utc)
                    if dp < cutoff:
                        skipped_old += 1
                        continue
                jobs.append(job_data)
            except Exception as e:
                print(f"Error parsing LinkedIn job: {e}")
                continue

        if jobs or skipped_old:
            print(f"LinkedIn: Found {len(jobs)} fresh jobs for '{keyword}' in '{location}'"
                  + (f" (skipped {skipped_old} older than 48h)" if skipped_old else ""))

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
                date_posted = datetime.utcnow()

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
            is_remote=is_remote
        )
