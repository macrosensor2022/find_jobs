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
    'india', 'singapore', 'japan', 'dubai', 'global', 'worldwide',
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
                'category': 'it',  # IT jobs only
                'limit': 50,
            }
            
            if keyword:
                params['search'] = keyword
            
            response = self.session.get(self.api_url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                all_jobs = data.get('jobs', [])
                
                for job in all_jobs:
                    job_location = job.get('candidate_required_location', '').lower()
                    
                    # Filter to USA only
                    if not self._is_usa_compatible(job_location):
                        continue
                    
                    jobs.append({
                        'title': job.get('title', ''),
                        'company': job.get('company_name', ''),
                        'location': job.get('candidate_required_location', 'Remote'),
                        'url': job.get('url', ''),
                        'description': job.get('description', ''),
                        'date_posted': self._parse_date(job.get('published_at', '')),
                        'source': 'remotive',
                    })
                
                logger.info(f"Remotive: Found {len(jobs)} USA jobs for '{keyword}'")
            else:
                logger.warning(f"Remotive API returned {response.status_code}")
                
        except Exception as e:
            logger.error(f"Remotive error: {str(e)}")
        
        return jobs
    
    def _is_usa_compatible(self, location: str) -> bool:
        """Check if location is USA or Remote"""
        if not location or location in ('remote', 'anywhere', 'worldwide', 'global'):
            return True
        
        # Check if it's clearly non-US
        for indicator in NON_US_INDICATORS:
            if indicator in location:
                return False
        
        # Check if it's USA
        for indicator in US_LOCATIONS:
            if indicator in location:
                return True
        
        # Default to allowing (might be remote)
        return True
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse Remotive date format"""
        if not date_str:
            return datetime.now(timezone.utc)
        
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return datetime.now(timezone.utc)
    
    def parse_job_listing(self, job_data: dict) -> dict:
        """Parse a single job listing"""
        return {
            'title': job_data.get('title', ''),
            'company': job_data.get('company_name', ''),
            'location': job_data.get('candidate_required_location', 'Remote'),
            'url': job_data.get('url', ''),
            'description': job_data.get('description', ''),
            'date_posted': self._parse_date(job_data.get('published_at', '')),
            'source': 'remotive',
        }
    
    def scrape(self, keywords: list = None, locations: list = None) -> list:
        """Scrape jobs from Remotive"""
        all_jobs = []
        
        keywords = keywords or ['AI', 'Machine Learning', 'Data Science']
        locations = locations or ['USA', 'Remote']
        
        for keyword in keywords:
            jobs = self.search_jobs(keyword=keyword)
            all_jobs.extend(jobs)
            time.sleep(0.5)
        
        return self._deduplicate_jobs(all_jobs)