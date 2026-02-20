"""
Indeed RSS Feed Scraper
Uses Indeed's RSS feeds for job searches - no authentication required
"""

from .base_scraper import BaseScraper
from datetime import datetime
import urllib.parse
import xml.etree.ElementTree as ET
import re
import time


class IndeedScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.source_name = "indeed"
        self.base_url = "https://www.indeed.com/rss"
    
    def search_jobs(self, keyword: str, location: str, page: int = 1) -> list:
        """
        Fetch jobs from Indeed RSS feed.
        """
        jobs = []
        
        try:
            # Build RSS URL
            params = {
                'q': keyword,
                'l': location,
                'sort': 'date',  # Sort by date (most recent first)
                'fromage': '7',  # Last 7 days
                'limit': 50,     # Max results
                'start': (page - 1) * 50
            }
            
            url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
            
            time.sleep(1)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse RSS XML
            root = ET.fromstring(response.content)
            
            # Find all job items
            items = root.findall('.//item')
            
            for item in items:
                parsed = self.parse_job_listing(item)
                if parsed:
                    jobs.append(parsed)
            
            print(f"Indeed RSS: Found {len(jobs)} jobs for '{keyword}' in '{location}'")
            
        except ET.ParseError as e:
            print(f"Error parsing Indeed RSS: {e}")
        except Exception as e:
            print(f"Error fetching Indeed RSS: {e}")
        
        return jobs
    
    def parse_job_listing(self, item: ET.Element) -> dict:
        """Parse an RSS item into a job dict"""
        
        def get_text(tag):
            elem = item.find(tag)
            return elem.text.strip() if elem is not None and elem.text else ''
        
        title = get_text('title')
        link = get_text('link')
        
        # Indeed format: "Company - Location"
        source_text = get_text('source')
        
        # Parse company from source or title
        company = ''
        if source_text:
            company = source_text
        
        # Try to extract location from the formatted location field
        location = ''
        # Indeed sometimes includes location in georss:point or formatted text
        geo = item.find('.//{http://www.georss.org/georss}point')
        if geo is not None and geo.text:
            location = "See job posting"  # Coordinates not useful
        
        # Parse description
        description = get_text('description')
        
        # Clean HTML from description
        description = self._clean_html(description)
        
        # Extract company and location from description if not found
        if not company or not location:
            # Indeed descriptions often start with location info
            lines = description.split('\n')
            for line in lines[:3]:
                if ' - ' in line and not company:
                    parts = line.split(' - ')
                    if len(parts) >= 2:
                        company = parts[0].strip()
                        location = parts[1].strip()
                        break
        
        # Parse date
        pub_date = get_text('pubDate')
        date_posted = None
        if pub_date:
            try:
                # RSS date format: "Thu, 20 Feb 2026 10:30:00 GMT"
                from email.utils import parsedate_to_datetime
                date_posted = parsedate_to_datetime(pub_date)
            except:
                date_posted = datetime.utcnow()
        
        # Check if remote
        is_remote = 'remote' in title.lower() or 'remote' in description.lower()
        
        # Extract job ID from URL
        external_id = ''
        jk_match = re.search(r'jk=([a-f0-9]+)', link)
        if jk_match:
            external_id = jk_match.group(1)
        
        if not title:
            return None
        
        return self.create_job_dict(
            title=title,
            company=company or 'See posting',
            location=location or 'See posting',
            description=description,
            job_url=link,
            date_posted=date_posted,
            is_remote=is_remote,
            external_id=external_id
        )
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text"""
        if not text:
            return ''
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Clean up whitespace
        clean = re.sub(r'\s+', ' ', clean)
        # Decode HTML entities
        import html
        clean = html.unescape(clean)
        return clean.strip()
