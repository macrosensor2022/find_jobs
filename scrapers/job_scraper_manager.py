from datetime import datetime, timezone
from typing import List, Dict
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.remoteok_scraper import RemoteOKScraper
from scrapers.themuse_scraper import TheMuseScraper
from scrapers.arbeitnow_scraper import ArbeitnowScraper
from scrapers.remotive_scraper import RemotiveScraper
from scrapers.ats_scraper import AtsBoardScraper, GreenhouseScraper, LeverScraper, AshbyScraper
from scrapers.adzuna_scraper import AdzunaScraper
from scrapers.jsearch_scraper import JSearchScraper
from scrapers.github_simplify_scraper import GithubNewGradScraper, GithubInternScraper
from scrapers.profile_matcher import ProfileMatcher
from scrapers.sponsorship_data import lookup_employer
from scrapers.location_utils import (
    canonicalize_location, in_target_states, persist_unparsed,
)
from scrapers.metro_opportunity import (
    lookup_opportunity_score, compute_competition_score, compute_rank_score,
)
from backend.models import Job, SearchLog, SearchRun, SourceRun

# NUWorks is disabled from the normal workflow (Selenium + Duo login). The
# module is imported lazily so a missing Selenium install cannot break scrapes.
try:
    from scrapers.nuworks_scraper import NUWorksScraper
except Exception:  # pragma: no cover - optional dependency
    NUWorksScraper = None
from services.dedupe import (
    build_dedupe_key, normalize_url, prefer as prefer_source,
)
from services.freshness import is_expired as freshness_is_expired
from services.ranking import apply_to_model, score_job
import re


def _normalize_title(title: str) -> str:
    t = (title or '').lower().strip()
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


class JobScraperManager:
    def __init__(self, db_session, min_match_score: int = 30, progress_callback=None):
        self.db_session = db_session
        self.min_match_score = min_match_score
        self.profile_matcher = ProfileMatcher()
        self.progress_callback = progress_callback
        
        # Working scrapers (no API key required)
        self.scrapers = {
            'linkedin': LinkedInScraper(),
            'remoteok': RemoteOKScraper(),
            'themuse': TheMuseScraper(),
            'arbeitnow': ArbeitnowScraper(),
            'remotive': RemotiveScraper(),
            'ats': AtsBoardScraper(),
            'greenhouse': GreenhouseScraper(),
            'lever': LeverScraper(),
            'ashby': AshbyScraper(),
            'adzuna': AdzunaScraper(),
            'jsearch': JSearchScraper(),
            'github_newgrad': GithubNewGradScraper(),
            'github_intern': GithubInternScraper(),
        }
        self.nuworks_scraper = None
        self._watchlist_cache = None
        self._location_prefs_cache = None

    def init_nuworks(self, username: str = None, password: str = None):
        """Opt-in only. NUWorks is excluded from the normal workflow."""
        from config.settings import Config

        if not getattr(Config, 'NUWORKS_ENABLED', False):
            raise RuntimeError(
                'NUWorks is disabled. Set NUWORKS_ENABLED=true to enable it.'
            )
        if NUWorksScraper is None:
            raise RuntimeError('NUWorks scraper is unavailable in this build.')
        self.nuworks_scraper = NUWorksScraper(username, password)
        self.scrapers['nuworks'] = self.nuworks_scraper

    def _watchlist(self):
        """Target companies from the DB, falling back to the config seed."""
        if self._watchlist_cache is not None:
            return self._watchlist_cache
        from config.settings import Config

        entries = []
        try:
            from backend.models import WatchlistCompany
            rows = WatchlistCompany.query.filter_by(is_active=True).all()
            entries = [{'name': r.name, 'priority': r.priority} for r in rows]
        except Exception:
            entries = []
        if not entries:
            entries = [
                {'name': name, 'priority': 2}
                for name in getattr(Config, 'WATCHLIST_COMPANIES', [])
            ]
        self._watchlist_cache = entries
        return entries

    def _location_prefs(self):
        """User-editable location prefs from the DB, else config defaults."""
        if self._location_prefs_cache is not None:
            return self._location_prefs_cache
        prefs = None
        try:
            from backend.models import Preference
            row = Preference.query.filter_by(key='location_preferences').first()
            if row and isinstance(row.parsed, dict):
                prefs = row.parsed
        except Exception:
            prefs = None
        self._location_prefs_cache = prefs or {}
        return self._location_prefs_cache

    def _apply_location_prefs_to_scrapers(self):
        """Keep source-level location skips in sync with the UI prefs."""
        from config.settings import Config

        prefs = self._location_prefs()
        excluded = prefs.get('excluded_states') or getattr(Config, 'EXCLUDED_STATES', [])
        for name in ('github_newgrad', 'github_intern'):
            scraper = self.scrapers.get(name)
            if scraper is not None:
                scraper.excluded_states = list(excluded)

    def _filter_and_score(self, jobs: List[Dict], min_score: int) -> List[Dict]:
        """Score discovered jobs and keep the ones worth storing.

        The same engine that powers the UI decides acceptance, so a job's
        stored score always matches the reason it was kept. Quality is not a
        gate here — it only affects ranking — because a thin description at
        discovery time is not a reason to discard a real posting.
        """
        accepted = []
        for job_data in jobs:
            if not isinstance(job_data, dict) or not job_data.get('title'):
                continue
            try:
                result = score_job(
                    job_data,
                    watchlist=self._watchlist(),
                    location_prefs=self._location_prefs() or None,
                )
            except Exception:
                logger.exception('Scoring failed for %s', job_data.get('title'))
                continue
            match = result['match']
            job_data['match_score'] = result['candidate_match_score']
            job_data['final_score'] = result['final_score']
            job_data['exp_hard_drop'] = match['experience']['hard_drop']
            job_data['matched_skills'] = match['skills']['matched']
            if not match['eligible']:
                continue
            if result['candidate_match_score'] >= min_score:
                accepted.append(job_data)
        accepted.sort(key=lambda j: j.get('final_score') or 0, reverse=True)
        return accepted

    def _merge_duplicate(self, existing: Job, job_data: dict, new_source: str):
        """Fold a duplicate into the stored job, preferring official postings."""
        import json
        from datetime import datetime, timezone

        new_url = job_data.get('job_url') or job_data.get('application_url')
        if new_url:
            known = set()
            if existing.alt_source_urls:
                try:
                    known = set(json.loads(existing.alt_source_urls) or [])
                except (ValueError, TypeError):
                    known = set()
            if new_url != existing.job_url and new_url not in known:
                known.add(new_url)
                existing.alt_source_urls = json.dumps(sorted(known)[:10])

        # A company ATS posting beats an aggregator copy of the same job.
        if prefer_source(existing.source, new_source):
            existing.source = new_source
            if new_url:
                existing.job_url = new_url
                existing.source_url = job_data.get('source_url') or new_url
                existing.application_url = job_data.get('application_url') or new_url
                existing.application_url_status = (
                    job_data.get('application_url_status') or 'unverified'
                )
            if job_data.get('external_id'):
                existing.external_id = job_data['external_id']

        # Fill in facts we did not previously have. Never overwrite a known
        # value with an unknown one.
        if existing.date_posted is None and job_data.get('date_posted'):
            existing.date_posted = job_data['date_posted']
            existing.date_posted_origin = job_data.get('date_posted_origin') or 'feed'
        elif job_data.get('date_posted') and existing.date_posted:
            # Prefer a newer known posting date when the feed has one
            incoming = job_data['date_posted']
            current = existing.date_posted
            if getattr(incoming, 'tzinfo', None) is None:
                from datetime import timezone as _tz
                incoming = incoming.replace(tzinfo=_tz.utc)
            if getattr(current, 'tzinfo', None) is None:
                from datetime import timezone as _tz
                current = current.replace(tzinfo=_tz.utc)
            if incoming > current:
                existing.date_posted = job_data['date_posted']
                existing.date_posted_origin = job_data.get('date_posted_origin') or 'feed'

        if not existing.application_url and job_data.get('application_url'):
            existing.application_url = job_data['application_url']
            existing.application_url_status = (
                job_data.get('application_url_status') or 'unverified'
            )
        if len(existing.description or '') < len(job_data.get('description') or ''):
            existing.description = job_data['description']
            existing.description_partial = job_data.get('description_partial')

        # Rediscovery: bump scrape time so "today / this week" filters and the
        # morning briefing treat the job as freshly seen again.
        existing.date_scraped = datetime.now(timezone.utc)
        try:
            from services.freshness import evaluate as evaluate_freshness, is_expired
            fresh = evaluate_freshness(existing.date_posted)
            existing.freshness_hours = fresh.get('hours')
            existing.freshness_bucket = fresh.get('bucket')
            existing.is_expired = bool(is_expired(existing.date_posted))
        except Exception:
            logger.debug('Freshness refresh failed for job %s', existing.id, exc_info=True)
    def _job_matches_locations(self, job_data: dict, locations: List[str]) -> bool:
        """Return True when a job location matches any requested location."""
        if not locations:
            return True

        job_location = (job_data.get('location') or '').lower()
        if not job_location:
            return False

        normalized_location = job_location.replace('.', '').replace(',', ' ')
        compact_location = normalized_location.replace(' ', '')

        location_aliases = {
            'united states': ['united states', 'usa', 'u.s.', 'u.s.a', 'us'],
            'usa': ['united states', 'usa', 'u.s.', 'u.s.a', 'us'],
            'maine': ['maine', 'me', 'portland me', 'portland maine'],
            'new york': ['new york', 'ny', 'nyc'],
            'new jersey': ['new jersey', 'nj'],
            'texas': ['texas', 'tx'],
            'colorado': ['colorado', 'co'],
            'utah': ['utah', 'ut'],
            'nevada': ['nevada', 'nv'],
            'arizona': ['arizona', 'az'],
            'california': ['california', 'ca'],
            'massachusetts': ['massachusetts', 'ma'],
            'washington': ['washington', 'wa'],
            'illinois': ['illinois', 'il'],
            'michigan': ['michigan', 'mi'],
            'ohio': ['ohio', 'oh'],
            'florida': ['florida', 'fl'],
            'remote': ['remote', 'anywhere', 'worldwide', 'global', 'work from home', 'wfh'],
        }

        for location in locations:
            location_key = (location or '').strip().lower()
            if not location_key:
                continue

            aliases = location_aliases.get(location_key, [location_key])
            for alias in aliases:
                alias_norm = alias.lower().replace('.', '').strip()
                alias_compact = alias_norm.replace(' ', '')
                if alias_norm in normalized_location or alias_compact in compact_location:
                    return True

        return False

    def _job_exists(self, source: str, job_data: dict):
        """Find an existing job using stable IDs before fuzzy matching.

        Order: external_id+source → job_url (any source) → company+title+location
        (cross-source, normalized title) to collapse JSearch aggregator triplicates.
        """
        external_id = (job_data.get('external_id') or '').strip()
        job_url = (job_data.get('job_url') or '').strip()
        title = (job_data.get('title') or '').strip()
        company = (job_data.get('company') or '').strip()
        location = (job_data.get('location') or '').strip()

        if external_id:
            existing = Job.query.filter_by(source=source, external_id=external_id).first()
            if existing:
                return existing

        # Cross-source URL dedup (JSearch / Adzuna / ATS often share apply links)
        if job_url:
            existing = Job.query.filter_by(job_url=job_url).first()
            if existing:
                return existing
            normalized = normalize_url(job_url)
            if normalized:
                for candidate in Job.query.filter(
                    Job.job_url.ilike(f'%{normalized.split("/")[-1]}%')
                ).limit(25).all():
                    if normalize_url(candidate.job_url) == normalized:
                        return candidate

        # Identity key: same employer + same role + same place, any source.
        key = build_dedupe_key(job_data)
        if key:
            existing = Job.query.filter_by(dedupe_key=key).first()
            if existing:
                return existing

        if company and title:
            norm = _normalize_title(title)
            candidates = Job.query.filter(
                Job.company.ilike(company),
            ).all()
            for c in candidates:
                if _normalize_title(c.title or '') == norm:
                    # Same company + title; location soft-match
                    if not location or not c.location:
                        return c
                    if location.lower() in (c.location or '').lower() or \
                       (c.location or '').lower() in location.lower():
                        return c

        return Job.query.filter_by(
            source=source,
            title=title,
            company=company,
            location=location,
        ).first()
    
    def scrape_source(self, source: str, keywords: List[str], locations: List[str]) -> Dict:
        if source not in self.scrapers:
            return {'error': f'Unknown source: {source}', 'jobs_found': 0}
        
        scraper = self.scrapers[source]
        total_jobs = 0
        new_jobs = 0
        matched_jobs = 0
        duplicates = 0
        missing_apply_url = 0
        match_scores = []
        errors = []

        # LinkedIn uses keyword × location iteration — cap locations to avoid
        # 150+ page crawls.
        if source == 'linkedin':
            from config.settings import Config as _Cfg
            locations = getattr(_Cfg, 'LINKEDIN_LOCATIONS', locations[:5])
        
        api_scrapers = ['remoteok', 'themuse', 'arbeitnow', 'usajobs', 'remotive',
                        'ats', 'greenhouse', 'lever', 'ashby', 'adzuna', 'jsearch',
                        'github_newgrad', 'github_intern']

        if source in api_scrapers:
            log = SearchLog(
                source=source,
                keyword=','.join(keywords[:3]) if keywords else source,
                location='USA+IN' if source in ('adzuna', 'jsearch') else 'USA',
                status='in_progress'
            )
            self.db_session.add(log)
            self.db_session.commit()

            try:
                all_jobs = []
                if source in ('ats', 'greenhouse', 'lever', 'ashby', 'adzuna', 'jsearch',
                              'github_newgrad', 'github_intern'):
                    # One budgeted fan-out pass (scrape ignores keyword loops)
                    scraper_obj = self.scrapers[source]
                    if hasattr(scraper_obj, 'scrape'):
                        all_jobs = scraper_obj.scrape(keywords=keywords, locations=locations)
                    else:
                        all_jobs = scraper_obj.search_jobs()
                else:
                    for keyword in keywords:
                        jobs = scraper.search_jobs(keyword=keyword)
                        all_jobs.extend(jobs)
                
                if source in ('ats', 'greenhouse', 'lever', 'ashby', 'adzuna', 'jsearch',
                              'github_newgrad', 'github_intern'):
                    location_filtered = all_jobs
                else:
                    location_filtered = [
                        job for job in all_jobs if self._job_matches_locations(job, locations)
                    ]

                matched = self._filter_and_score(location_filtered, self.min_match_score)
                total_jobs += len(location_filtered)
                matched_jobs += len(matched)
                
                for job_data in matched:
                    job_source = job_data.get('source') or source
                    match_scores.append(job_data.get('match_score') or 0)
                    if not job_data.get('application_url') and not job_data.get('job_url'):
                        missing_apply_url += 1
                    existing = self._job_exists(job_source, job_data)

                    if not existing:
                        job = self._create_job_from_data(job_data, job_source)
                        try:
                            self._enrich_job_with_opt_data(job, job_data)
                        except Exception as enrich_err:
                            logger.warning(
                                'Enrichment failed for %s @ %s: %s',
                                job.title, job.company, enrich_err,
                            )
                        self.db_session.add(job)
                        new_jobs += 1
                        # Release SQLite write lock often so the UI stays responsive
                        if new_jobs % 10 == 0:
                            self.db_session.commit()
                    else:
                        duplicates += 1
                        self._merge_duplicate(existing, job_data, job_source)
                    
                log.jobs_found = len(location_filtered)
                log.status = 'success'
                log.completed_at = datetime.now(timezone.utc)

                # Surface call-budget usage in error_message field for ops visibility
                if source in ('adzuna', 'jsearch'):
                    used = getattr(self.scrapers[source], 'calls_used', None)
                    cap = getattr(self.scrapers[source], 'max_calls', None)
                    if used is not None:
                        log.error_message = f'calls_used={used}/{cap}'
                        logger.info(f'{source}: calls_used={used}/{cap}')
                
            except Exception as e:
                log.status = 'failed'
                log.error_message = str(e)
                log.completed_at = datetime.now(timezone.utc)
                errors.append(str(e))
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
            
            try:
                self.db_session.commit()
            except Exception as commit_err:
                logger.exception('Commit failed for %s: %s', source, commit_err)
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
                errors.append(f'commit: {commit_err}')
            try:
                persist_unparsed(self.db_session)
            except Exception:
                pass
        else:
            # Standard keyword + location iteration (LinkedIn, etc.)
            # Cap LinkedIn keywords so a huge UI selection cannot hang the server forever
            scrape_keywords = keywords
            if source == 'linkedin' and len(keywords) > 6:
                scrape_keywords = keywords[:6]
                logger.info(
                    'LinkedIn: capping keywords from %d to %d for this run',
                    len(keywords), len(scrape_keywords),
                )

            total_pairs = max(1, len(scrape_keywords) * len(locations))
            pair_i = 0
            for keyword in scrape_keywords:
                for location in locations:
                    pair_i += 1
                    if self.progress_callback:
                        try:
                            self.progress_callback({
                                'current_source': source,
                                'message': (
                                    f'{source}: {keyword} @ {location} '
                                    f'({pair_i}/{total_pairs})'
                                ),
                                'pair': pair_i,
                                'pairs_total': total_pairs,
                            })
                        except Exception:
                            pass

                    log = SearchLog(
                        source=source,
                        keyword=keyword,
                        location=location,
                        status='in_progress'
                    )
                    self.db_session.add(log)
                    self.db_session.commit()
                    
                    try:
                        jobs = scraper.search_jobs(keyword, location)
                        
                        # Filter by match score
                        matched = self._filter_and_score(jobs, self.min_match_score)
                        total_jobs += len(jobs)
                        matched_jobs += len(matched)
                        
                        for job_data in matched:
                            match_scores.append(job_data.get('match_score') or 0)
                            if not job_data.get('job_url'):
                                missing_apply_url += 1
                            existing = self._job_exists(source, job_data)

                            if not existing:
                                job = self._create_job_from_data(job_data, source)
                                try:
                                    self._enrich_job_with_opt_data(job, job_data)
                                except Exception as enrich_err:
                                    logger.warning(
                                        'Enrichment failed for %s @ %s: %s',
                                        job.title, job.company, enrich_err,
                                    )
                                self.db_session.add(job)
                                new_jobs += 1
                            else:
                                duplicates += 1
                                self._merge_duplicate(existing, job_data, source)
                            
                        log.jobs_found = len(jobs)
                        log.status = 'success'
                        log.completed_at = datetime.now(timezone.utc)
                        
                    except Exception as e:
                        log.status = 'failed'
                        log.error_message = str(e)
                        log.completed_at = datetime.now(timezone.utc)
                        errors.append(f"{keyword}@{location}: {str(e)}")
                        try:
                            self.db_session.rollback()
                        except Exception:
                            pass
                    
                    try:
                        self.db_session.commit()
                    except Exception as commit_err:
                        logger.exception(
                            'Commit failed for %s %s@%s: %s',
                            source, keyword, location, commit_err,
                        )
                        try:
                            self.db_session.rollback()
                        except Exception:
                            pass
        
        return {
            'source': source,
            'total_found': total_jobs,
            'matched_jobs': matched_jobs,
            'new_jobs': new_jobs,
            'duplicates': duplicates,
            'missing_apply_url': missing_apply_url,
            'avg_match': (
                round(sum(match_scores) / len(match_scores), 1) if match_scores else None
            ),
            'errors': errors
        }
    
    def _create_job_from_data(self, job_data: dict, source: str) -> Job:
        """Create a Job model instance from job data dict."""
        date_posted = job_data.get('date_posted')
        freshness_hours = None
        if date_posted:
            dp = date_posted
            if dp.tzinfo is None:
                dp = dp.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dp
            freshness_hours = max(0, int(delta.total_seconds() / 3600))

        job_url = job_data.get('job_url')
        application_url = job_data.get('application_url')
        if application_url is None:
            application_url = job_url or None

        return Job(
            title=job_data.get('title'),
            company=job_data.get('company'),
            location=job_data.get('location'),
            description=job_data.get('description'),
            job_url=job_url,
            source=source,
            salary_min=job_data.get('salary_min'),
            salary_max=job_data.get('salary_max'),
            job_type=job_data.get('job_type', 'full-time'),
            date_posted=date_posted,
            is_remote=job_data.get('is_remote', False),
            external_id=job_data.get('external_id'),
            match_score=job_data.get('match_score', 0),
            freshness_hours=freshness_hours,
            market=job_data.get('market'),
            salary_predicted=job_data.get('salary_predicted'),
            description_partial=job_data.get('description_partial'),
            source_url=job_data.get('source_url') or job_url or None,
            application_url=application_url,
            application_url_status=job_data.get('application_url_status') or (
                'unverified' if application_url else 'unknown'
            ),
            date_posted_origin=job_data.get('date_posted_origin') or (
                'feed' if date_posted else 'unknown'
            ),
            dedupe_key=build_dedupe_key(job_data),
            verification_status='unverified',
        )

    def _enrich_job_with_opt_data(self, job: Job, job_data: dict):
        """Add OPT intelligence + metro opportunity fields before saving.

        India (market=IN) skips sponsorship / LCA / metro — ranks on match + recency only.
        """
        from config.settings import Config

        market = (job_data.get('market') or job.market or 'US').upper()
        if market in ('IND', 'INDIA'):
            market = 'IN'
        job.market = market
        job.salary_predicted = job_data.get('salary_predicted')
        job.description_partial = job_data.get('description_partial')

        # Resolve the worksite before scoring so the location dimension can use
        # a real state instead of re-parsing the raw text.
        loc = canonicalize_location(job.location or '')
        job.worksite_city = loc.get('city')
        job.worksite_state = loc.get('state')
        job.metro = loc.get('metro')
        job.metro_code = loc.get('metro_code')

        # Age-based expiry, only when we actually know the posting date.
        job.is_expired = freshness_is_expired(job.date_posted)

        # Explainable scoring: seven weighted dimensions + opportunity +
        # quality, each stored with the evidence behind it.
        job.dedupe_key = job.dedupe_key or build_dedupe_key(job_data)
        scoring = score_job({
            'title': job.title,
            'company': job.company,
            'location': job.location,
            'description': job.description,
            'source': job.source,
            'date_posted': job.date_posted,
            'is_remote': job.is_remote,
            'worksite_state': loc.get('state'),
            'salary_min': job.salary_min,
            'salary_max': job.salary_max,
            'salary_predicted': job.salary_predicted,
            'description_partial': job.description_partial,
            'application_url': job.application_url,
            'application_url_status': job.application_url_status,
            'verification_status': job.verification_status,
            'is_expired': job.is_expired,
            'duplicate_of_id': job.duplicate_of_id,
            'competition_score': job.competition_score,
            'sponsorship_hint': job_data.get('sponsorship_hint'),
        }, watchlist=self._watchlist(), location_prefs=self._location_prefs() or None)
        apply_to_model(job, scoring)

        # Hide only genuine disqualifiers (experience / role / authorization).
        # Excluded states are scored via location_blocked so the user can change
        # location prefs in the UI without jobs being permanently hard-hidden.
        if not scoring['match']['eligible']:
            job.is_hidden = True

        preferred = (
            (self._location_prefs() or {}).get('preferred_states')
            or getattr(Config, 'PREFERRED_STATES', None)
            or getattr(Config, 'TARGET_STATES', [])
        )
        job.in_target_states = in_target_states(
            loc.get('state'), preferred, allow_remote=True,
        )

        job.opt_field_related = (job.match_score or 0) >= Config.OPT_FIELD_MATCH_MIN

        if market == 'IN':
            # Skip US sponsorship / DOL-LCA / metro opportunity entirely
            job.is_everify = None
            job.h1b_lca_count = None
            job.wage_level = None
            job.employer_match_conf = None
            job.location_opportunity_score = None
            job.in_target_states = True  # do not hide India jobs via US state filter
            job.competition_score = compute_competition_score(
                {
                    'freshness_hours': job.freshness_hours,
                    'date_posted': job.date_posted,
                    'source': job.source,
                },
                source=job.source,
            )
            # Rank on match + recency only (no sponsor / location_opp penalty)
            job.opt_fit_score = job.match_score or 0
            job.rank_score = compute_rank_score(
                job.match_score,
                0.0,   # no sponsor confidence
                50.0,  # neutral location (not penalized for missing LCA)
                job.competition_score,
            )
            return

        # ---- US market: full OPT / metro pipeline ----
        emp = lookup_employer(job.company or '', self.db_session)
        job.is_everify = emp['is_everify']
        job.h1b_lca_count = emp['h1b_lca_count']
        job.wage_level = emp['wage_level']
        job.employer_match_conf = emp['employer_match_conf']

        job.opt_fit_score = ProfileMatcher.compute_opt_fit_score(
            job.match_score, job.is_everify,
            job.sponsorship_screen, job.opt_field_related,
        )

        opp = lookup_opportunity_score(self.db_session, job.metro_code)
        job.location_opportunity_score = opp
        job.competition_score = compute_competition_score(
            {
                'freshness_hours': job.freshness_hours,
                'date_posted': job.date_posted,
                'source': job.source,
            },
            source=job.source,
        )
        job.rank_score = compute_rank_score(
            job.match_score,
            job.employer_match_conf,
            job.location_opportunity_score,
            job.competition_score,
        )
    
    def scrape_all(self, sources: List[str] = None, keywords: List[str] = None,
                   locations: List[str] = None, trigger: str = 'manual') -> Dict:
        from config.settings import Config
        
        if sources is None:
            sources = list(getattr(Config, 'DAILY_SOURCES', [
                'github_newgrad', 'adzuna', 'jsearch', 'ats', 'remoteok', 'themuse',
            ]))
        if keywords is None:
            keywords = Config.SEARCH_KEYWORDS[:5]
        if locations is None:
            locations = Config.TARGET_LOCATIONS

        # NUWorks never participates unless explicitly enabled.
        if not getattr(Config, 'NUWORKS_ENABLED', False):
            sources = [s for s in sources if s != 'nuworks']

        self._apply_location_prefs_to_scrapers()

        # Fast API / ATS / GitHub feeds first; LinkedIn last (slow + flaky DNS)
        priority = [
            'github_newgrad', 'github_intern',
            'adzuna', 'jsearch', 'ats', 'greenhouse', 'lever', 'ashby',
            'remoteok', 'themuse', 'remotive', 'arbeitnow', 'usajobs',
            'linkedin', 'nuworks',
        ]
        sources = sorted(
            sources,
            key=lambda s: priority.index(s) if s in priority else 50,
        )
        
        results = {
            'started_at': datetime.now(timezone.utc).isoformat(),
            'sources': {},
            'total_new_jobs': 0,
            'total_matched_jobs': 0,
            'min_match_score': self.min_match_score
        }

        search_run = self._start_search_run(sources, keywords, trigger)
        if search_run is not None:
            results['search_run_id'] = search_run.id

        sources_done = []
        for source in sources:
            if self.progress_callback:
                try:
                    self.progress_callback({
                        'current_source': source,
                        'sources_done': list(sources_done),
                        'sources_total': len(sources),
                        'message': f'Scraping {source}…',
                        'total_new_jobs': results['total_new_jobs'],
                        'total_matched_jobs': results['total_matched_jobs'],
                    })
                except Exception:
                    pass

            if source == 'nuworks' and source not in self.scrapers:
                results['sources'][source] = {
                    'error': 'NUWorks is disabled in this configuration.',
                    'jobs_found': 0,
                    'disabled': True,
                }
                sources_done.append(source)
                continue
            
            if source not in self.scrapers:
                results['sources'][source] = {
                    'error': f'Unknown source: {source}',
                    'jobs_found': 0
                }
                sources_done.append(source)
                continue
            
            try:
                result = self.scrape_source(source, keywords, locations)
            except Exception as e:
                logger.exception('scrape_source(%s) crashed', source)
                result = {
                    'source': source,
                    'total_found': 0,
                    'matched_jobs': 0,
                    'new_jobs': 0,
                    'errors': [str(e)],
                    'error': str(e),
                }
                try:
                    self.db_session.rollback()
                except Exception:
                    pass

            results['sources'][source] = result
            results['total_new_jobs'] += result.get('new_jobs', 0)
            results['total_matched_jobs'] += result.get('matched_jobs', 0)
            sources_done.append(source)
            self._record_source_run(search_run, source, result)

            if self.progress_callback:
                try:
                    self.progress_callback({
                        'current_source': source,
                        'sources_done': list(sources_done),
                        'sources_total': len(sources),
                        'message': (
                            f'Finished {source}: '
                            f'{result.get("new_jobs", 0)} new / '
                            f'{result.get("matched_jobs", 0)} matched'
                        ),
                        'total_new_jobs': results['total_new_jobs'],
                        'total_matched_jobs': results['total_matched_jobs'],
                        'partial_results': {
                            'sources': results['sources'],
                            'total_new_jobs': results['total_new_jobs'],
                            'total_matched_jobs': results['total_matched_jobs'],
                        },
                    })
                except Exception:
                    pass
        
        results['completed_at'] = datetime.now(timezone.utc).isoformat()
        self._finish_search_run(search_run, results)

        return results

    def _start_search_run(self, sources, keywords, trigger):
        """Open a SearchRun row so every run is auditable afterwards."""
        import json

        try:
            run = SearchRun(
                trigger=trigger or 'manual',
                status='running',
                sources=json.dumps(list(sources)),
                keywords=json.dumps(list(keywords or [])),
            )
            self.db_session.add(run)
            self.db_session.commit()
            return run
        except Exception:
            logger.warning('Could not open SearchRun row', exc_info=True)
            try:
                self.db_session.rollback()
            except Exception:
                pass
            return None

    def _record_source_run(self, search_run, source, result):
        try:
            row = SourceRun(
                search_run_id=search_run.id if search_run is not None else None,
                source=source,
                status='failed' if result.get('errors') or result.get('error') else 'success',
                jobs_discovered=result.get('total_found', 0),
                jobs_accepted=result.get('new_jobs', 0),
                duplicates=result.get('duplicates', 0),
                missing_apply_url=result.get('missing_apply_url', 0),
                avg_match=result.get('avg_match'),
                error_message='; '.join(result.get('errors') or [])[:2000] or None,
                completed_at=datetime.now(timezone.utc),
            )
            self.db_session.add(row)
            self.db_session.commit()
        except Exception:
            logger.warning('Could not record SourceRun for %s', source, exc_info=True)
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def _finish_search_run(self, search_run, results):
        if search_run is None:
            return
        from config.settings import Config

        try:
            per_source = results.get('sources') or {}
            errors = [
                f'{name}: {"; ".join(data.get("errors") or [])}'
                for name, data in per_source.items()
                if data.get('errors') or data.get('error')
            ]
            discovered = sum(d.get('total_found', 0) for d in per_source.values())
            duplicates = sum(d.get('duplicates', 0) for d in per_source.values())
            averages = [
                d['avg_match'] for d in per_source.values()
                if d.get('avg_match') is not None
            ]

            strong = Job.query.filter(
                Job.candidate_match_score >= Config.STRONG_MATCH_MIN,
                Job.scored_at >= search_run.started_at,
            ).count()
            excellent = Job.query.filter(
                Job.candidate_match_score >= Config.EXCELLENT_MATCH_MIN,
                Job.scored_at >= search_run.started_at,
            ).count()

            search_run.status = 'completed'
            search_run.jobs_discovered = discovered
            search_run.jobs_accepted = results.get('total_new_jobs', 0)
            search_run.duplicates = duplicates
            search_run.avg_match = (
                round(sum(averages) / len(averages), 1) if averages else None
            )
            search_run.strong_matches = strong
            search_run.excellent_matches = excellent
            search_run.error_count = len(errors)
            search_run.error_summary = '\n'.join(errors)[:4000] or None
            search_run.completed_at = datetime.now(timezone.utc)
            self.db_session.commit()
        except Exception:
            logger.warning('Could not finalize SearchRun', exc_info=True)
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def close(self):
        if self.nuworks_scraper:
            self.nuworks_scraper.close()


def run_scraper_cli():
    import argparse
    from flask import Flask
    from backend.models import db
    from config.settings import Config
    
    parser = argparse.ArgumentParser(description='Job Scraper CLI')
    parser.add_argument('--sources', nargs='+', default=['remoteok', 'themuse'],
                        help='Sources to scrape')
    parser.add_argument('--keywords', nargs='+', help='Search keywords')
    parser.add_argument('--locations', nargs='+', help='Locations to search')
    parser.add_argument('--min-match', type=int, default=30, help='Minimum match score (default: 30)')
    parser.add_argument('--nuworks', action='store_true', help='Include NUWorks (requires credentials)')
    
    args = parser.parse_args()
    
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        
        manager = JobScraperManager(db.session, min_match_score=args.min_match)
        
        if args.nuworks:
            manager.init_nuworks()
            args.sources.append('nuworks')
        
        results = manager.scrape_all(
            sources=args.sources,
            keywords=args.keywords,
            locations=args.locations
        )
        
        print("\n=== Scraping Results ===")
        print(f"Started: {results['started_at']}")
        print(f"Completed: {results['completed_at']}")
        print(f"Minimum Match Score: {results['min_match_score']}%")
        print(f"Total New Jobs (40%+ match): {results['total_new_jobs']}")
        print("\nBy Source:")
        for source, data in results['sources'].items():
            if 'error' in data:
                print(f"  {source}: {data['error']}")
            else:
                print(f"  {source}: {data.get('new_jobs', 0)} new jobs, {data.get('matched_jobs', 0)} matched (errors: {len(data.get('errors', []))})")
        
        manager.close()


if __name__ == '__main__':
    run_scraper_cli()
