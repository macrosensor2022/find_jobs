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
from scrapers.nuworks_scraper import NUWorksScraper
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
from backend.models import Job, SearchLog
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
    
    def init_nuworks(self, username: str = None, password: str = None):
        self.nuworks_scraper = NUWorksScraper(username, password)
        self.scrapers['nuworks'] = self.nuworks_scraper

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

                matched = self.profile_matcher.filter_jobs_by_match(location_filtered, self.min_match_score)
                total_jobs += len(location_filtered)
                matched_jobs += len(matched)
                
                for job_data in matched:
                    job_source = job_data.get('source') or source
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
                        matched = self.profile_matcher.filter_jobs_by_match(jobs, self.min_match_score)
                        total_jobs += len(jobs)
                        matched_jobs += len(matched)
                        
                        for job_data in matched:
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

        return Job(
            title=job_data.get('title'),
            company=job_data.get('company'),
            location=job_data.get('location'),
            description=job_data.get('description'),
            job_url=job_data.get('job_url'),
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

        # Experience gate (all markets)
        exp = self.profile_matcher.evaluate_experience({
            'title': job.title,
            'description': job.description,
        })
        job.required_years = exp.get('required_years')
        job.exp_hard_drop = exp.get('hard_drop')
        if exp.get('hard_drop'):
            job.is_hidden = True
            job.match_score = 0

        job.sponsorship_screen = self.profile_matcher.detect_sponsorship_screen(
            job.title, job.description,
        )
        # SimplifyJobs feed often includes an explicit sponsorship field
        hint = (job_data.get('sponsorship_hint') or '').lower()
        if hint in ('no_sponsorship', 'citizenship_required'):
            job.sponsorship_screen = True
        job.opt_field_related = (job.match_score or 0) >= Config.OPT_FIELD_MATCH_MIN

        if market == 'IN':
            # Skip US sponsorship / DOL-LCA / metro opportunity entirely
            job.is_everify = None
            job.h1b_lca_count = None
            job.wage_level = None
            job.employer_match_conf = None
            job.location_opportunity_score = None
            job.metro = None
            job.metro_code = None
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

        loc = canonicalize_location(job.location or '')
        job.worksite_city = loc.get('city')
        job.worksite_state = loc.get('state')
        job.metro = loc.get('metro')
        job.metro_code = loc.get('metro_code')
        target_states = getattr(Config, 'TARGET_STATES', [])
        job.in_target_states = in_target_states(
            loc.get('state'), target_states, allow_remote=True,
        )
        if loc.get('state') in getattr(Config, 'EXCLUDED_STATES', ['CA', 'WA', 'OR']):
            job.is_hidden = True
            job.in_target_states = False
        elif loc.get('parse_ok') and loc.get('state') and not job.in_target_states:
            if loc.get('state') != 'REMOTE':
                job.is_hidden = True

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
    
    def scrape_all(self, sources: List[str] = None, keywords: List[str] = None, locations: List[str] = None) -> Dict:
        from config.settings import Config
        
        if sources is None:
            sources = ['github_newgrad', 'adzuna', 'jsearch', 'ats', 'remoteok', 'themuse']
        if keywords is None:
            keywords = Config.SEARCH_KEYWORDS[:5]
        if locations is None:
            locations = Config.TARGET_LOCATIONS

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
                    'error': 'NUWorks requires credentials. Use the NUWorks login section.',
                    'jobs_found': 0
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
        
        return results
    
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
