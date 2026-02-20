"""
Adzuna API Scraper
Requires free API key from https://developer.adzuna.com/
Falls back to basic scraping if no API key
"""

from .base_scraper import BaseScraper
from datetime import datetime
import urllib.parse
import os
import time


class AdzunaScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "adzuna"
        self.api_url = "https://api.adzuna.com/v1/api/jobs/us/search"
        self.app_id = os.getenv('ADZUNA_APP_ID', '')
        self.app_key = os.getenv('ADZUNA_APP_KEY', '')
        self.session.headers.update({
            'Accept': 'application/json',
        })
    
    def search_jobs(self, keyword: str, location: str = None, page: int = 1) -> list:
        """
        Fetch jobs from Adzuna API.
        If no API credentials, returns empty list with message.
        """
        jobs = []
        
        if not self.app_id or not self.app_key:
            print("Adzuna: No API credentials. Set ADZUNA_APP_ID and ADZUNA_APP_KEY env vars.")
            print("Get free API key at: https://developer.adzuna.com/")
            return jobs
        
        try:
            params = {
                'app_id': self.app_id,
                'app_key': self.app_key,
                'results_per_page': 50,
                'what': keyword,
                'what_or': 'intern internship co-op',
                'max_days_old': 14,
                'sort_by': 'date',
            }
            
            if location:
                params['where'] = location
            
            url = f"{self.api_url}/{page}?{urllib.parse.urlencode(params)}"
            
            time.sleep(0.5)
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                
                for job_data in results:
                    parsed = self.parse_job_listing(job_data)
                    if parsed:
                        jobs.append(parsed)
                
                print(f"Adzuna: Found {len(jobs)} jobs for '{keyword}'" + (f" in '{location}'" if location else ""))
            else:
                print(f"Adzuna API error: {response.status_code}")
            
        except Exception as e:
            print(f"Error fetching Adzuna jobs: {e}")
        
        return jobs
    
    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None
        
        title = job_data.get('title', '')
        
        # Company
        company_data = job_data.get('company', {})
        company = company_data.get('display_name', '') if isinstance(company_data, dict) else ''
        
        # Location
        location_data = job_data.get('location', {})
        location = ''
        if isinstance(location_data, dict):
            area = location_data.get('area', [])
            if area:
                location = ', '.join(area[-2:])  # City, State typically
            else:
                location = location_data.get('display_name', '')
        
        # URL
        job_url = job_data.get('redirect_url', '')
        
        # Description
        description = job_data.get('description', '')
        
        # Date
        date_posted = None
        created = job_data.get('created')
        if created:
            try:
                date_posted = datetime.fromisoformat(created.replace('Z', '+00:00'))
            except:
                date_posted = datetime.utcnow()
        
        # Salary
        salary_min = job_data.get('salary_min')
        salary_max = job_data.get('salary_max')
        
        # Category
        category = job_data.get('category', {})
        if isinstance(category, dict) and category.get('label'):
            description = f"{description}\n\nCategory: {category['label']}"
        
        if not title:
            return None
        
        return self.create_job_dict(
            title=title,
            company=company or 'See posting',
            location=location or 'See posting',
            description=description,
            job_url=job_url,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
            is_remote='remote' in title.lower() or 'remote' in location.lower(),
            external_id=str(job_data.get('id', ''))
        )
