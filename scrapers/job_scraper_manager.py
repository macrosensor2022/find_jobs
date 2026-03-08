from datetime import datetime
from typing import List, Dict
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.remoteok_scraper import RemoteOKScraper
from scrapers.themuse_scraper import TheMuseScraper
from scrapers.adzuna_scraper import AdzunaScraper
from scrapers.arbeitnow_scraper import ArbeitnowScraper
from scrapers.usajobs_scraper import USAJobsScraper
from scrapers.nuworks_scraper import NUWorksScraper
from scrapers.profile_matcher import ProfileMatcher
from backend.models import Job, SearchLog


class JobScraperManager:
    def __init__(self, db_session, min_match_score: int = 30):
        self.db_session = db_session
        self.min_match_score = min_match_score
        self.profile_matcher = ProfileMatcher()
        
        self.scrapers = {
            'linkedin': LinkedInScraper(),
            'remoteok': RemoteOKScraper(),
            'themuse': TheMuseScraper(),
            'adzuna': AdzunaScraper(),
            'arbeitnow': ArbeitnowScraper(),
            'usajobs': USAJobsScraper(),
        }
        self.nuworks_scraper = None
    
    def init_nuworks(self, username: str = None, password: str = None):
        self.nuworks_scraper = NUWorksScraper(username, password)
        self.scrapers['nuworks'] = self.nuworks_scraper
    
    def scrape_source(self, source: str, keywords: List[str], locations: List[str]) -> Dict:
        if source not in self.scrapers:
            return {'error': f'Unknown source: {source}', 'jobs_found': 0}
        
        scraper = self.scrapers[source]
        total_jobs = 0
        new_jobs = 0
        matched_jobs = 0
        errors = []
        
        api_scrapers = ['remoteok', 'themuse', 'arbeitnow', 'usajobs']

        if source in api_scrapers:
            log = SearchLog(
                source=source,
                keyword=','.join(keywords[:3]),
                location='USA',
                status='in_progress'
            )
            self.db_session.add(log)
            self.db_session.commit()

            try:
                all_jobs = []
                for keyword in keywords:
                    jobs = scraper.search_jobs(keyword=keyword)
                    all_jobs.extend(jobs)
                
                # Filter by match score
                matched = self.profile_matcher.filter_jobs_by_match(all_jobs, self.min_match_score)
                
                for job_data in matched:
                    existing = Job.query.filter_by(
                        source=source,
                        title=job_data.get('title'),
                        company=job_data.get('company')
                    ).first()
                    
                    if not existing:
                        job = self._create_job_from_data(job_data, source)
                        self.db_session.add(job)
                        new_jobs += 1
                    
                    total_jobs += 1
                    matched_jobs += 1
                
                log.jobs_found = len(all_jobs)
                log.status = 'success'
                log.completed_at = datetime.utcnow()
                
            except Exception as e:
                log.status = 'failed'
                log.error_message = str(e)
                log.completed_at = datetime.utcnow()
                errors.append(str(e))
            
            self.db_session.commit()
        else:
            # Standard keyword + location iteration
            for keyword in keywords:
                for location in locations:
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
                        
                        for job_data in matched:
                            existing = Job.query.filter_by(
                                source=source,
                                title=job_data.get('title'),
                                company=job_data.get('company')
                            ).first()
                            
                            if not existing:
                                job = self._create_job_from_data(job_data, source)
                                self.db_session.add(job)
                                new_jobs += 1
                            
                            total_jobs += 1
                            matched_jobs += 1
                        
                        log.jobs_found = len(jobs)
                        log.status = 'success'
                        log.completed_at = datetime.utcnow()
                        
                    except Exception as e:
                        log.status = 'failed'
                        log.error_message = str(e)
                        log.completed_at = datetime.utcnow()
                        errors.append(f"{keyword}@{location}: {str(e)}")
                    
                    self.db_session.commit()
        
        return {
            'source': source,
            'total_found': total_jobs,
            'matched_jobs': matched_jobs,
            'new_jobs': new_jobs,
            'errors': errors
        }
    
    def _create_job_from_data(self, job_data: dict, source: str) -> Job:
        """Create a Job model instance from job data dict"""
        return Job(
            title=job_data.get('title'),
            company=job_data.get('company'),
            location=job_data.get('location'),
            description=job_data.get('description'),
            job_url=job_data.get('job_url'),
            source=source,
            salary_min=job_data.get('salary_min'),
            salary_max=job_data.get('salary_max'),
            job_type=job_data.get('job_type', 'internship'),
            date_posted=job_data.get('date_posted'),
            is_remote=job_data.get('is_remote', False),
            external_id=job_data.get('external_id'),
            match_score=job_data.get('match_score', 0)
        )
    
    def scrape_all(self, sources: List[str] = None, keywords: List[str] = None, locations: List[str] = None) -> Dict:
        from config.settings import Config
        
        if sources is None:
            sources = ['linkedin', 'remoteok', 'themuse']
        if keywords is None:
            keywords = Config.SEARCH_KEYWORDS[:5]
        if locations is None:
            locations = Config.TARGET_LOCATIONS
        
        results = {
            'started_at': datetime.utcnow().isoformat(),
            'sources': {},
            'total_new_jobs': 0,
            'total_matched_jobs': 0,
            'min_match_score': self.min_match_score
        }
        
        for source in sources:
            if source == 'nuworks' and source not in self.scrapers:
                results['sources'][source] = {
                    'error': 'NUWorks requires credentials. Use the NUWorks login section.',
                    'jobs_found': 0
                }
                continue
            
            if source not in self.scrapers:
                results['sources'][source] = {
                    'error': f'Unknown source: {source}',
                    'jobs_found': 0
                }
                continue
            
            result = self.scrape_source(source, keywords, locations)
            results['sources'][source] = result
            results['total_new_jobs'] += result.get('new_jobs', 0)
            results['total_matched_jobs'] += result.get('matched_jobs', 0)
        
        results['completed_at'] = datetime.utcnow().isoformat()
        
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
