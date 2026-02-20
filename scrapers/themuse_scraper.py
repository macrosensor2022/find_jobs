"""
The Muse API Scraper
Free public API - no authentication required for basic access
https://www.themuse.com/developers/api/v2
"""

from .base_scraper import BaseScraper
from datetime import datetime
import urllib.parse
import time


class TheMuseScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "themuse"
        self.api_url = "https://www.themuse.com/api/public/jobs"
        self.session.headers.update({
            'Accept': 'application/json',
        })
    
    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        """
        Fetch jobs from The Muse API.
        """
        jobs = []
        
        try:
            params = {
                'page': page - 1,  # The Muse uses 0-indexed pages
                'descending': 'true',
            }
            
            # Add category filter for relevant roles
            categories = [
                'Data Science',
                'Data and Analytics', 
                'Software Engineering',
                'IT'
            ]
            
            # Add location filter
            if location:
                params['location'] = location
            
            # Add level filter for internships/entry-level
            params['level'] = 'Internship'
            
            time.sleep(0.5)
            
            all_jobs = []
            
            # Search with different categories
            for category in categories:
                params['category'] = category
                
                url = f"{self.api_url}?{urllib.parse.urlencode(params, doseq=True)}"
                
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    
                    for job_data in results:
                        parsed = self.parse_job_listing(job_data)
                        if parsed:
                            # Filter by keyword if provided
                            if keyword:
                                keyword_lower = keyword.lower()
                                if keyword_lower not in parsed['title'].lower() and \
                                   keyword_lower not in (parsed.get('description') or '').lower():
                                    continue
                            
                            all_jobs.append(parsed)
                
                time.sleep(0.3)
            
            # Also search for entry-level positions
            params['level'] = 'Entry Level'
            for category in categories[:2]:  # Just data categories
                params['category'] = category
                
                url = f"{self.api_url}?{urllib.parse.urlencode(params, doseq=True)}"
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    
                    for job_data in results:
                        parsed = self.parse_job_listing(job_data)
                        if parsed:
                            if keyword:
                                keyword_lower = keyword.lower()
                                if keyword_lower not in parsed['title'].lower() and \
                                   keyword_lower not in (parsed.get('description') or '').lower():
                                    continue
                            all_jobs.append(parsed)
                
                time.sleep(0.3)
            
            # Deduplicate by job URL
            seen_urls = set()
            for job in all_jobs:
                if job['job_url'] not in seen_urls:
                    seen_urls.add(job['job_url'])
                    jobs.append(job)
            
            print(f"The Muse: Found {len(jobs)} jobs" + (f" matching '{keyword}'" if keyword else ""))
            
        except Exception as e:
            print(f"Error fetching The Muse jobs: {e}")
        
        return jobs
    
    def parse_job_listing(self, job_data: dict) -> dict:
        if not isinstance(job_data, dict):
            return None
        
        title = job_data.get('name', '')
        
        # Company info
        company_data = job_data.get('company', {})
        company = company_data.get('name', '') if isinstance(company_data, dict) else ''
        
        # Location - The Muse returns a list of location objects
        locations = job_data.get('locations', [])
        location_str = ''
        if locations:
            location_names = [loc.get('name', '') for loc in locations if isinstance(loc, dict)]
            location_str = ', '.join(filter(None, location_names))
        
        # Job URL
        refs = job_data.get('refs', {})
        job_url = refs.get('landing_page', '') if isinstance(refs, dict) else ''
        
        # Description/contents
        description = job_data.get('contents', '')
        
        # Publication date
        date_posted = None
        pub_date = job_data.get('publication_date')
        if pub_date:
            try:
                date_posted = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
            except:
                date_posted = datetime.utcnow()
        
        # Check if remote
        is_remote = 'remote' in location_str.lower() or 'flexible' in location_str.lower()
        
        # Categories/tags
        categories = job_data.get('categories', [])
        if categories:
            cat_names = [c.get('name', '') for c in categories if isinstance(c, dict)]
            if cat_names:
                description = f"{description}\n\nCategories: {', '.join(cat_names)}"
        
        # Levels
        levels = job_data.get('levels', [])
        if levels:
            level_names = [l.get('name', '') for l in levels if isinstance(l, dict)]
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
