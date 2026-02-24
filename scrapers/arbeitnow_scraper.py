"""
Arbeitnow API Scraper
Free API for tech/remote jobs - no key required
"""

from .base_scraper import BaseScraper
from datetime import datetime
import time


class ArbeitnowScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "arbeitnow"
        self.api_url = "https://www.arbeitnow.com/api/job-board-api"
    
    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        jobs = []
        
        try:
            time.sleep(1)
            response = self.session.get(self.api_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            all_jobs = data.get('data', [])
            
            for job in all_jobs:
                if keyword:
                    title = (job.get('title') or '').lower()
                    desc = (job.get('description') or '').lower()
                    tags = ' '.join(job.get('tags', [])).lower()
                    
                    if keyword.lower() not in f"{title} {desc} {tags}":
                        continue
                
                parsed = self.parse_job_listing(job)
                if parsed:
                    jobs.append(parsed)
            
            print(f"Arbeitnow: Found {len(jobs)} jobs" + (f" matching '{keyword}'" if keyword else ""))
            
        except Exception as e:
            print(f"Arbeitnow error: {e}")
        
        return jobs
    
    def parse_job_listing(self, job: dict) -> dict:
        return self.create_job_dict(
            title=job.get('title', ''),
            company=job.get('company_name', ''),
            location=job.get('location', 'Remote'),
            description=job.get('description', ''),
            job_url=job.get('url', ''),
            date_posted=None,
            is_remote=job.get('remote', False),
            external_id=str(job.get('slug', ''))
        )
