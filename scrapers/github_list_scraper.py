"""Golden new-grad source adapters.

SpeedyApply (AI / SWE) and Zapply (Data-Science / New-Grad) publish new-grad
job lists as raw GitHub markdown tables (no API key). This module turns those
tables into the same canonical job dict the existing pipeline consumes, so the
new sources flow through the SAME normalization / dedup / freshness /
sponsorship / classification / scoring / ranking engines.

Two table families are handled by one reusable adapter:
  * SpeedyApply:  Company | Position | Salary | Location | Posting | Age
                  (the "Other" section and the AI feed order columns differently)
  * Zapply:       Company | Role | Location | Posted | Visa | Apply

All row fields are kept as provenance in `source_metadata`; the posting age
(Age / Posted) becomes a real `date_posted` with `date_posted_origin='posted'`
so the existing freshness engine buckets it. Zapply's Visa column is captured
as *evidence* (visa_evidence) and is never converted into a sponsorship
guarantee on its own.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# SpeedyApply posting-age column ("0d", "117d", "1d", "3w")
_AGE_RE = re.compile(r'(\d+)\s*(d|w|h)', re.I)
# Zapply Posted column ("5m", "6m") — minutes
_POSTED_MIN_RE = re.compile(r'(\d+)\s*m\b', re.I)
_POSTED_H_RE = re.compile(r'(\d+)\s*h\b', re.I)


_MARKDOWN_LINK_RE = re.compile(r'\]\(\s*(https?://[^\s)]+)\s*\)', re.I)
_HTML_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _strip_anchor(html):
    """Pull the href from a Markdown/HTML link cell, else ''.

    Zapply uses Markdown image links `[<img ...>](https://...)`.
    SpeedyApply uses raw HTML `<a href="https://...">`.
    """
    if not html:
        return ''
    m = _HTML_LINK_RE.search(html)
    if m:
        return m.group(1)
    m = _MARKDOWN_LINK_RE.search(html)
    if m:
        return m.group(1)
    return html.strip(' \t*')


def _strip_company(html):
    """Extract the company name from a Markdown `<strong>` cell, else raw text."""
    if not html:
        return ''
    m = re.search(r'<strong>([^<]+)</strong>', html)
    if m:
        return m.group(1).strip()
    return html.strip(' \t*|').strip()


def _split_row(line: str, headers: List[str]) -> Optional[dict]:
    """Parse a Markdown table data row into a dict keyed by header order."""
    if not line or '|' not in line:
        return None
    if re.match(r'^\s*\|[\s\-\t|:]+\|?\s*$', line):
        return None
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    if len(cells) < len(headers):
        return None
    return {h: cells[i] for i, h in enumerate(headers)}


def _age_to_ts(value: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Convert an Age / Posted cell to a posted datetime.

    SpeedyApply ages are days/hours/weeks ("0d", "36h", "117d", "3w").
    Zapply Posted is minutes ("5m", "6m").
    Returns None when the value cannot be interpreted — calling code must then
    fall back to discovery time (never a guess). Precision is not preserved
    beyond the source's own granularity; the existing freshness engine buckets
    on this.
    """
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    v = str(value).strip().lower()
    m = _POSTED_MIN_RE.search(v)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = _POSTED_H_RE.search(v)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = _AGE_RE.search(v)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit == 'w':
            return now - timedelta(weeks=n)
        if unit == 'h':
            return now - timedelta(hours=n)
        if unit == 'd':
            return now - timedelta(days=n)
    return None


class GithubListSourceAdapter(BaseScraper):
    """Reusable adapter for a GitHub markdown-table job list.

    Configure per source with:
      repository    - owner/repo
      source_id     - the DAILY_SOURCES id (e.g. "github_speedyapply_ai_2027")
      category      - loose bucket (ai-ml / swe / ds), for metadata only
      enabled       - participates in schedulers / DAILY_SOURCES
    """

    source_type = 'curated_community_github'
    headers: List[str] = []

    def __init__(self, repository: str, source_id: str, category: str = '',
                 enabled: bool = True, **kwargs):
        super().__init__()
        self.repository = repository
        self.source_id = source_id
        self.source_name = source_id
        self.category = category or ''
        self.enabled = enabled
        self.session.headers.update({
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'JobTracker/1.0 (personal job search)',
        })

    # ------------------------------------------------------------------ API ---
    def search_jobs(self, keyword: str = None, location: str = None,
                    page: int = 1) -> list:
        return self.scrape()

    def scrape(self, keywords: list = None, locations: list = None) -> list:
        if not self.enabled:
            logger.info('%s: disabled, returning []', self.source_id)
            return []
        try:
            text = self._fetch_table()
        except Exception as e:
            logger.warning('%s: fetch failed: %s', self.source_id, e)
            return []
        jobs, seen = [], set()
        for line in self._iter_table_lines(text):
            parsed = self._parse_line(line)
            if not parsed:
                continue
            key = parsed.get('external_id') or parsed.get('application_url') or ''
            if not key or key in seen:
                continue
            seen.add(key)
            jobs.append(parsed)
        logger.info('%s: %d jobs from %s', self.source_id, len(jobs), self.repository)
        return jobs

    # ------------------------------------------------------------ overridable --
    def _raw_url(self) -> str:
        return f'https://raw.githubusercontent.com/{self.repository}/main/README.md'

    def _fetch_table(self) -> str:
        import requests as _r
        r = _r.get(self._raw_url(), timeout=45)
        r.raise_for_status()
        return r.text

    def _parse_line(self, line: str) -> Optional[dict]:
        raise NotImplementedError

    def parse_job_listing(self, listing) -> Optional[dict]:
        """Satisfy the BaseScraper contract. `scrape()` drives parsing row-wise."""
        if isinstance(listing, str):
            return self._parse_line(listing)
        return None

    # --------------------------------------------------------------- helpers ---
    def _iter_table_lines(self, text: str):
        """Yield data rows after any `| Company …` header that matches ours."""
        in_table = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith('| Company'):
                hdrs = [c.strip() for c in line.strip().strip('|').split('|')]
                in_table = len(hdrs) >= 2 and hdrs[0] == 'Company'
                continue
            if not in_table:
                continue
            if line.startswith('<!--') and ('TABLE' in line or 'END' in line):
                if 'START' in line:
                    continue
                in_table = False
                continue
            if line.startswith('|'):
                yield line
                continue
            # a non-table, non-link line ends the current table block
            if not line.lower().startswith(('![', '[')):
                in_table = False


class SpeedyApplyAdapter(GithubListSourceAdapter):
    """SpeedyApply 2027 tables.

    Headers vary by section:
      6-col: Company | Position | Location | Salary | Posting | Age
      5-col: Company | Position | Location | Posting | Age  (the "Other" section)
    We map Position/Location/Age; Posting holds the apply link.
    """
    headers6 = ['Company', 'Position', 'Location', 'Salary', 'Posting', 'Age']
    headers5 = ['Company', 'Position', 'Location', 'Posting', 'Age']

    def _parse_line(self, line):
        row6 = _split_row(line, self.headers6)
        row = row6 or _split_row(line, self.headers5)
        if not row:
            return None
        company = _strip_company(row.get('Company', ''))
        position = row.get('Position', '')
        location = row.get('Location', '')
        age = row.get('Age', '')
        posting = _strip_anchor(row.get('Posting', ''))
        salary = row.get('Salary', '')

        if not position or not company:
            return None

        posted = _age_to_ts(age)
        job = self.create_job_dict(
            title=position.strip(),
            company=company.strip(),
            location=location.strip() or 'Remote',
            description=f'Source list: {self.repository}. Listing on {self.category or "new-grad"} '
                        f'board; {salary or "salary n/a"}.',
            job_url='',
            application_url=posting,
            job_type='full-time',
            date_posted=posted,
            date_posted_origin='posted' if posted else 'unknown',
            is_remote='remote' in location.lower(),
            external_id=posting or f'{company}|{position}',
            market='US',
            description_partial=True,
        )
        job['source_metadata'] = {
            'repository': self.repository,
            'source_id': self.source_id,
            'posting_age_raw': age.strip(),
            'salary_raw': (salary or '').strip(),
            'location_raw': location.strip(),
        }
        return job


class ZapplyAdapter(GithubListSourceAdapter):
    """Zapply tables: Company | Role | Location | Posted | Visa | Apply."""
    headers = ['Company', 'Role', 'Location', 'Posted', 'Visa', 'Apply']

    def _parse_line(self, line):
        row = _split_row(line, self.headers)
        if not row:
            return None
        company = _strip_company(row.get('Company', ''))
        role = row.get('Role', '')
        location = row.get('Location', '')
        posted = row.get('Posted', '')
        visa = row.get('Visa', '')
        apply = _strip_anchor(row.get('Apply', ''))

        if not role or not company:
            return None

        date = _age_to_ts(posted)
        job = self.create_job_dict(
            title=role.strip(),
            company=company.strip(),
            location=location.strip(),
            description=f'Source: {self.repository}. Title: {role}',
            job_url=apply,
            application_url=apply,
            job_type='full-time',
            date_posted=date,
            date_posted_origin='posted' if date else 'unknown',
            is_remote='remote' in location.lower(),
            external_id=apply or f'{company}|{role}',
            market='US',
            description_partial=True,
        )
        # Visa column is EVIDENCE, captured raw. Never a sponsorship guarantee.
        if visa:
            job['visa_evidence_raw'] = visa.strip()
            job['source_metadata'] = {
                'repository': self.repository,
                'source_id': self.source_id,
                'visa_raw': visa.strip(),
                'posted_raw': posted,
            }
            v = visa.lower()
            if 'does not sponsor' in v:
                job['sponsorship_hint'] = 'does_not_offer_sponsorship'
            elif 'sponsor' in v and 'h-1b' not in v:
                job['sponsorship_hint'] = 'offers_sponsorship'
        return job