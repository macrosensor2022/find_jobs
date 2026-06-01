from abc import ABC, abstractmethod
from datetime import datetime, timezone
import requests
import certifi
from bs4 import BeautifulSoup
import time
import random
import logging
import ssl
from functools import wraps

logger = logging.getLogger(__name__)


def _build_ssl_context():
    """
    Build an SSL context that works across environments.

    Strategy (try in order, first success wins):
    1. `truststore` — uses the OS native trust store. Can trigger
       RecursionError on some Windows / Python 3.13 configurations.
    2. `certifi` — vendored Mozilla CA bundle.
    3. Disable verification — last resort when the system trust store
       has certs Python's strict validation rejects (e.g. BasicConstraints
       not marked critical). Logs a warning.

    Returns a value for `requests.Session.verify`.
    """
    _ts = None
    # --- attempt 1: truststore ---
    try:
        import truststore as _ts
        _ts.inject_into_ssl()
        requests.head('https://www.google.com', timeout=10)
        logger.info("SSL: using OS native trust store (truststore)")
        return True
    except ImportError:
        logger.debug("truststore not installed")
    except RecursionError:
        logger.warning("truststore caused RecursionError, reverting")
        if _ts:
            try:
                _ts.extract_from_ssl()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"truststore failed ({e}), reverting")
        if _ts:
            try:
                _ts.extract_from_ssl()
            except Exception:
                pass

    # --- attempt 2: certifi bundle (test against a real scraper target) ---
    try:
        ca_path = certifi.where()
        requests.head('https://remoteok.com', verify=ca_path, timeout=10)
        logger.info("SSL: using certifi CA bundle")
        return ca_path
    except Exception as e:
        logger.warning(f"certifi verification also failed ({e})")

    # --- attempt 3: no verification (local-dev fallback) ---
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logger.warning(
        "SSL: certificate verification disabled — all HTTPS requests "
        "will be unverified. This is safe for local development but "
        "should not be used in production."
    )
    return False


_SSL_VERIFY = _build_ssl_context()


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
        self.session.verify = _SSL_VERIFY
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
            'job_type': kwargs.get('job_type', 'full-time'),
            'date_posted': kwargs.get('date_posted'),
            'is_remote': kwargs.get('is_remote', False),
            'external_id': kwargs.get('external_id', ''),
        }
    
    def parse_relative_date(self, date_str: str) -> datetime:
        from datetime import timedelta

        date_str = date_str.lower().strip()
        now = datetime.now(timezone.utc)

        if 'just now' in date_str or 'moment' in date_str:
            return now
        elif 'minute' in date_str:
            minutes = self._extract_number(date_str)
            return now - timedelta(minutes=minutes)
        elif 'hour' in date_str:
            hours = self._extract_number(date_str)
            return now - timedelta(hours=hours)
        elif 'day' in date_str:
            days = self._extract_number(date_str)
            return now - timedelta(days=days)
        elif 'week' in date_str:
            weeks = self._extract_number(date_str)
            return now - timedelta(weeks=weeks)
        elif 'month' in date_str:
            months = self._extract_number(date_str)
            return now - timedelta(days=months * 30)
        elif 'year' in date_str:
            years = self._extract_number(date_str)
            return now - timedelta(days=years * 365)

        return now
    
    def _extract_number(self, text: str) -> int:
        import re
        numbers = re.findall(r'\d+', text)
        return int(numbers[0]) if numbers else 1
