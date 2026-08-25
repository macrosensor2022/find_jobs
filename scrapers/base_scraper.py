from abc import ABC, abstractmethod
from datetime import datetime, timezone
import os
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
    Build an SSL verify setting for requests.Session.

    Do NOT use truststore.inject_into_ssl() — on several Windows / Python
    setups it passes a local context probe but then raises
    RecursionError on every real HTTPS call (which zeroed out all scrapes).

    Prefer certifi's CA bundle; fall back to verify=False for local dev.
    """
    # If a previous import injected truststore, try to undo it
    try:
        import truststore as _ts
        try:
            _ts.extract_from_ssl()
        except Exception:
            pass
    except ImportError:
        pass

    try:
        ca_path = certifi.where()
        if ca_path and os.path.exists(ca_path):
            logger.info("SSL: using certifi CA bundle")
            return ca_path
    except Exception as e:
        logger.warning(f"certifi setup failed ({e})")

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logger.warning(
        "SSL: certificate verification disabled — all HTTPS requests "
        "will be unverified. This is safe for local development but "
        "should not be used in production."
    )
    return False


_SSL_VERIFY = _build_ssl_context()


def _is_non_retryable(exc: Exception) -> bool:
    """DNS / connection-name failures won't heal with sleep — fail fast."""
    if isinstance(exc, RecursionError):
        return True
    msg = str(exc).lower()
    markers = (
        'getaddrinfo failed',
        'nameresolutionerror',
        'failed to resolve',
        'nodename nor servname',
        'name or service not known',
        'maximum recursion depth exceeded',
    )
    return any(m in msg for m in markers)


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
                    if _is_non_retryable(e):
                        logger.error(f"Non-retryable network error (giving up): {e}")
                        raise
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

    def safe_get(self, url: str, **kwargs):
        """GET with SSL fallback (RecursionError / cert verify failures)."""
        timeout = kwargs.pop('timeout', 30)
        try:
            return self.session.get(url, timeout=timeout, **kwargs)
        except (RecursionError, requests.exceptions.SSLError) as e:
            logger.warning(
                "SSL issue on GET (%s) — retrying once with verify=False", e
            )
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False
            return self.session.get(url, timeout=timeout, verify=False, **kwargs)
    
    @abstractmethod
    def search_jobs(self, keyword: str, location: str, page: int = 1) -> list:
        pass
    
    @abstractmethod
    def parse_job_listing(self, listing) -> dict:
        pass
    
    @retry_on_failure(max_retries=3, backoff_factor=3.0)
    def get_page(self, url: str) -> BeautifulSoup:
        time.sleep(random.uniform(2, 5))
        try:
            response = self.safe_get(url, timeout=30)
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
            'market': kwargs.get('market'),
            'salary_predicted': kwargs.get('salary_predicted'),
            'description_partial': kwargs.get('description_partial', False),
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
