from abc import ABC, abstractmethod
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import time
import random
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def retry_on_failure(max_retries=3, backoff_factor=1.0):
    """Decorator to retry a function on failure with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed: {e}")
            raise last_exception
        return wrapper
    return decorator


class BaseScraper(ABC):
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        })
        self.source_name = "base"
    
    @abstractmethod
    def search_jobs(self, keyword: str, location: str, page: int = 1) -> list:
        pass
    
    @abstractmethod
    def parse_job_listing(self, listing) -> dict:
        pass
    
    @retry_on_failure(max_retries=3, backoff_factor=1.0)
    def get_page(self, url: str) -> BeautifulSoup:
        time.sleep(random.uniform(1, 3))
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            raise
    
    def create_job_dict(self, **kwargs) -> dict:
        return {
            'title': kwargs.get('title', ''),
            'company': kwargs.get('company', ''),
            'location': kwargs.get('location', ''),
            'description': kwargs.get('description', ''),
            'job_url': kwargs.get('job_url', ''),
            'source': self.source_name,
            'salary_min': kwargs.get('salary_min'),
            'salary_max': kwargs.get('salary_max'),
            'job_type': kwargs.get('job_type', 'internship'),
            'date_posted': kwargs.get('date_posted'),
            'is_remote': kwargs.get('is_remote', False),
            'external_id': kwargs.get('external_id', ''),
        }
    
    def parse_relative_date(self, date_str: str) -> datetime:
        date_str = date_str.lower().strip()
        now = datetime.now(timezone.utc)
        
        if 'just now' in date_str or 'moment' in date_str:
            return now
        elif 'hour' in date_str:
            hours = self._extract_number(date_str)
            new_hour = max(0, now.hour - hours)
            return now.replace(hour=new_hour)
        elif 'day' in date_str:
            days = self._extract_number(date_str)
            from datetime import timedelta
            return now - timedelta(days=days)
        elif 'week' in date_str:
            weeks = self._extract_number(date_str)
            from datetime import timedelta
            return now - timedelta(weeks=weeks)
        elif 'month' in date_str:
            months = self._extract_number(date_str)
            from datetime import timedelta
            return now - timedelta(days=months * 30)
        
        return now
    
    def _extract_number(self, text: str) -> int:
        import re
        numbers = re.findall(r'\d+', text)
        return int(numbers[0]) if numbers else 1
