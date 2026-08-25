"""
ATS-direct job board fetchers (Greenhouse, Lever, Ashby).

Public JSON APIs — no LinkedIn pressure. Boards configured in Config.ATS_BOARDS.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

DE_KEYWORDS = (
    'data engineer', 'analytics engineer', 'bi engineer', 'etl', 'ssis',
    'sql server', 'data analyst', 'business intelligence', 'power bi',
    'azure data', 'warehouse', 'pipeline',
)


def _title_relevant(title: str) -> bool:
    t = (title or '').lower()
    return any(k in t for k in DE_KEYWORDS)


class GreenhouseScraper(BaseScraper):
    def __init__(self, board_slug: str = None):
        super().__init__()
        self.source_name = 'greenhouse'
        self.board_slug = board_slug

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        # Used via AtsBoardScraper; single-board fetch if slug set
        if not self.board_slug:
            return []
        return self.fetch_board(self.board_slug)

    def fetch_board(self, slug: str) -> List[dict]:
        url = f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'
        try:
            resp = self.safe_get(url, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Greenhouse {slug}: HTTP {resp.status_code}")
                return []
            data = resp.json()
        except Exception as e:
            logger.warning(f"Greenhouse {slug}: {e}")
            return []

        jobs = []
        for item in data.get('jobs') or []:
            title = item.get('title') or ''
            if not _title_relevant(title):
                continue
            loc = ''
            locs = item.get('location') or {}
            if isinstance(locs, dict):
                loc = locs.get('name') or ''
            elif isinstance(locs, str):
                loc = locs
            offices = item.get('offices') or []
            if not loc and offices:
                loc = offices[0].get('name') or ''
            posted = None
            if item.get('updated_at'):
                try:
                    posted = datetime.fromisoformat(
                        item['updated_at'].replace('Z', '+00:00')
                    )
                except (ValueError, TypeError):
                    posted = None
            jobs.append({
                'title': title,
                'company': slug.replace('-', ' ').title(),
                'location': loc or 'Remote',
                'description': item.get('content') or '',
                'job_url': item.get('absolute_url') or '',
                'external_id': f"gh-{slug}-{item.get('id')}",
                'date_posted': posted,
                'is_remote': 'remote' in (loc or '').lower(),
                'job_type': 'full-time',
                'source': 'greenhouse',
            })
        logger.info(f"Greenhouse {slug}: {len(jobs)} DE-relevant jobs")
        return jobs

    def parse_job_listing(self, listing) -> dict:
        return listing if isinstance(listing, dict) else {}


class LeverScraper(BaseScraper):
    def __init__(self, board_slug: str = None):
        super().__init__()
        self.source_name = 'lever'
        self.board_slug = board_slug

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        if not self.board_slug:
            return []
        return self.fetch_board(self.board_slug)

    def fetch_board(self, slug: str) -> List[dict]:
        url = f'https://api.lever.co/v0/postings/{slug}?mode=json'
        try:
            resp = self.safe_get(url, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Lever {slug}: HTTP {resp.status_code}")
                return []
            data = resp.json()
            if not isinstance(data, list):
                data = data.get('data') or []
        except Exception as e:
            logger.warning(f"Lever {slug}: {e}")
            return []

        jobs = []
        for item in data:
            title = item.get('text') or item.get('title') or ''
            if not _title_relevant(title):
                continue
            cats = item.get('categories') or {}
            loc = cats.get('location') or item.get('location') or 'Remote'
            if isinstance(loc, list):
                loc = ', '.join(loc)
            posted = None
            created = item.get('createdAt')
            if created:
                try:
                    # Lever uses ms epoch
                    ts = int(created) / 1000.0 if int(created) > 1e12 else int(created)
                    posted = datetime.fromtimestamp(ts, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    posted = None
            jobs.append({
                'title': title,
                'company': slug.replace('-', ' ').title(),
                'location': loc or 'Remote',
                'description': item.get('descriptionPlain') or item.get('description') or '',
                'job_url': item.get('hostedUrl') or item.get('applyUrl') or '',
                'external_id': f"lever-{slug}-{item.get('id')}",
                'date_posted': posted,
                'is_remote': 'remote' in (loc or '').lower(),
                'job_type': 'full-time',
                'source': 'lever',
            })
        logger.info(f"Lever {slug}: {len(jobs)} DE-relevant jobs")
        return jobs

    def parse_job_listing(self, listing) -> dict:
        return listing if isinstance(listing, dict) else {}


class AshbyScraper(BaseScraper):
    def __init__(self, board_slug: str = None):
        super().__init__()
        self.source_name = 'ashby'
        self.board_slug = board_slug

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        if not self.board_slug:
            return []
        return self.fetch_board(self.board_slug)

    def fetch_board(self, slug: str) -> List[dict]:
        url = f'https://api.ashbyhq.com/posting-api/job-board/{slug}'
        try:
            resp = self.safe_get(url, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Ashby {slug}: HTTP {resp.status_code}")
                return []
            data = resp.json()
        except Exception as e:
            logger.warning(f"Ashby {slug}: {e}")
            return []

        jobs = []
        for item in data.get('jobs') or []:
            title = item.get('title') or ''
            if not _title_relevant(title):
                continue
            loc = item.get('location') or ''
            if not loc and item.get('address'):
                addr = item['address']
                if isinstance(addr, dict):
                    loc = ', '.join(filter(None, [
                        addr.get('postalAddress'), addr.get('addressLocality'),
                        addr.get('addressRegion'),
                    ]))
            posted = None
            if item.get('publishedAt'):
                try:
                    posted = datetime.fromisoformat(
                        str(item['publishedAt']).replace('Z', '+00:00')
                    )
                except (ValueError, TypeError):
                    posted = None
            jobs.append({
                'title': title,
                'company': slug.replace('-', ' ').title(),
                'location': loc or 'Remote',
                'description': item.get('descriptionPlain') or item.get('descriptionHtml') or '',
                'job_url': item.get('jobUrl') or item.get('applyUrl') or '',
                'external_id': f"ashby-{slug}-{item.get('id')}",
                'date_posted': posted,
                'is_remote': bool(item.get('isRemote')) or 'remote' in (loc or '').lower(),
                'job_type': 'full-time',
                'source': 'ashby',
            })
        logger.info(f"Ashby {slug}: {len(jobs)} DE-relevant jobs")
        return jobs

    def parse_job_listing(self, listing) -> dict:
        return listing if isinstance(listing, dict) else {}


class AtsBoardScraper(BaseScraper):
    """Fan-out scraper that hits all Config.ATS_BOARDS."""

    def __init__(self):
        super().__init__()
        self.source_name = 'ats'
        self._gh = GreenhouseScraper()
        self._lever = LeverScraper()
        self._ashby = AshbyScraper()

    def search_jobs(self, keyword: str = None, location: str = None, page: int = 1) -> list:
        from config.settings import Config
        boards = getattr(Config, 'ATS_BOARDS', []) or []
        all_jobs: List[dict] = []
        seen = set()
        for board in boards:
            platform = (board.get('platform') or '').lower()
            slug = board.get('slug')
            if not slug:
                continue
            if platform == 'greenhouse':
                jobs = self._gh.fetch_board(slug)
            elif platform == 'lever':
                jobs = self._lever.fetch_board(slug)
            elif platform == 'ashby':
                jobs = self._ashby.fetch_board(slug)
            else:
                continue
            for j in jobs:
                eid = j.get('external_id')
                if eid and eid in seen:
                    continue
                if eid:
                    seen.add(eid)
                # Prefer configured hint when location empty
                if not j.get('location') and board.get('hint'):
                    j['location'] = board['hint']
                all_jobs.append(j)
        return all_jobs

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        return self.search_jobs()

    def parse_job_listing(self, listing) -> dict:
        return listing if isinstance(listing, dict) else {}
