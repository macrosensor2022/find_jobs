"""
RemoteOK API Scraper
Free JSON API - no authentication required
https://remoteok.com/api
"""

from .base_scraper import BaseScraper
from datetime import datetime
import time


class RemoteOKScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "remoteok"
        self.api_url = "https://remoteok.com/api"
        self.session.headers.update({
            'Accept': 'application/json',
        })
    
    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        """
        Fetch jobs from RemoteOK API.
        Note: RemoteOK doesn't support keyword filtering via API, 
        so we fetch all and filter locally.
        """
        jobs = []
        
        try:
            time.sleep(1)  # Be nice to the API
            
            response = self.session.get(self.api_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # First item is usually metadata, skip it
            job_listings = data[1:] if len(data) > 1 else data
            
            for job_data in job_listings:
                parsed = self.parse_job_listing(job_data)
                if parsed:
                    # Filter by keyword if provided
                    if keyword:
                        keyword_lower = keyword.lower()
                        title_lower = parsed['title'].lower()
                        desc_lower = (parsed.get('description') or '').lower()
                        tags = ' '.join(job_data.get('tags', [])).lower()
                        
                        if keyword_lower not in title_lower and \
                           keyword_lower not in desc_lower and \
                           keyword_lower not in tags:
                            continue
                    
                    jobs.append(parsed)
            
            print(f"RemoteOK: Found {len(jobs)} jobs" + (f" matching '{keyword}'" if keyword else ""))
            
        except Exception as e:
            print(f"Error fetching RemoteOK jobs: {e}")
        
        return jobs
    
    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None
        
        # Skip if it's metadata/legal info
        if 'position' not in job_data and 'title' not in job_data:
            return None
        
        title = job_data.get('position') or job_data.get('title', '')
        company = job_data.get('company', '')
        location = job_data.get('location', 'Remote')
        
        # Build job URL
        slug = job_data.get('slug', '')
        job_url = f"https://remoteok.com/remote-jobs/{slug}" if slug else job_data.get('url', '')
        
        # Parse date
        date_posted = None
        if job_data.get('date'):
            try:
                # RemoteOK uses ISO format
                date_str = job_data['date']
                date_posted = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                date_posted = datetime.utcnow()
        
        # Get description
        description = job_data.get('description', '')
        
        # Salary info
        salary_min = job_data.get('salary_min')
        salary_max = job_data.get('salary_max')
        
        # Tags for better matching
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
    
    def get_all_jobs(self) -> list:
        """Get all available jobs without filtering"""
        return self.search_jobs()
