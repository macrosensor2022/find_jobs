"""
USAJobs API Scraper
Free API for US government jobs - no key required for basic searches
All results are guaranteed USA-based
"""

from .base_scraper import BaseScraper
from datetime import datetime
import time
import os


class USAJobsScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "usajobs"
        self.api_url = "https://data.usajobs.gov/api/search"
        auth_key = os.getenv('USAJOBS_API_KEY', '')
        self.session.headers.update({
            'Host': 'data.usajobs.gov',
            'User-Agent': os.getenv('USAJOBS_EMAIL', 'jobtracker@gmail.com'),
            'Authorization-Key': auth_key,
        })

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        jobs = []

        try:
            params = {
                'ResultsPerPage': 50,
                'Page': page,
                'SortField': 'DatePosted',
                'SortDirection': 'Desc',
                'JobCategoryCode': '2210',
            }

            if keyword:
                params['Keyword'] = keyword
            if location and location != 'United States':
                params['LocationName'] = location

            time.sleep(1)
            response = self.session.get(self.api_url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            results = data.get('SearchResult', {}).get('SearchResultItems', [])

            for item in results:
                job = item.get('MatchedObjectDescriptor', {})
                parsed = self.parse_job_listing(job)
                if parsed:
                    jobs.append(parsed)

            print(f"USAJobs: Found {len(jobs)} US government jobs" +
                  (f" for '{keyword}'" if keyword else ""))

        except Exception as e:
            print(f"USAJobs error: {e}")

        return jobs

    def parse_job_listing(self, job: dict) -> dict:
        locations = job.get('PositionLocation', [])
        location_str = locations[0].get('LocationName', 'USA') if locations else 'USA'

        salary_min = None
        salary_max = None
        remuneration = job.get('PositionRemuneration', [])
        if remuneration:
            salary_min = remuneration[0].get('MinimumRange')
            salary_max = remuneration[0].get('MaximumRange')

        return self.create_job_dict(
            title=job.get('PositionTitle', ''),
            company=job.get('OrganizationName', 'US Government'),
            location=location_str,
            description=job.get('UserArea', {}).get('Details', {}).get('JobSummary', ''),
            job_url=job.get('PositionURI', ''),
            date_posted=datetime.fromisoformat(job['PublicationStartDate'].replace('Z', '+00:00')) if job.get('PublicationStartDate') else None,
            salary_min=int(float(salary_min)) if salary_min else None,
            salary_max=int(float(salary_max)) if salary_max else None,
            is_remote='Remote' in location_str or 'Anywhere' in location_str,
            external_id=job.get('PositionID', '')
        )
