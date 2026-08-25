"""One-shot scrape: updates profile, scrapes all sources, prints results."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app import app
from backend.models import db, UserProfile
from scrapers.job_scraper_manager import JobScraperManager
from config.settings import Config

with app.app_context():
    # Update profile
    profile = UserProfile.query.first()
    if profile:
        profile.name = 'Vinay Varshigan SJ'
        profile.email = 'varsvinay911@gmail.com'
        profile.github_url = 'https://github.com/macrosensor2022'
        profile.linkedin_url = 'https://www.linkedin.com/in/vinaysj2003/'
        profile.target_role = (
            'Data Engineer / Analytics Engineer / BI Engineer '
            '(SQL Server, SSIS, Azure, Power BI) — Co-op, Internship, New Grad'
        )
        from datetime import date
        profile.grad_date = date(2027, 12, 15)
        profile.stem_eligible = True
        profile.unemployment_days = 0
        db.session.commit()
        print("Profile updated!")

    # Run scrapes in sequence
    manager = JobScraperManager(db.session, min_match_score=25)

    all_results = {}

    # 1) API scrapers first (fast)
    api_sources = ['remoteok', 'themuse', 'arbeitnow', 'remotive']
    combined_kw = Config.SEARCH_KEYWORDS[:8] + Config.SEARCH_KEYWORDS_INTERN[:6]

    for source in api_sources:
        print(f"\n--- Scraping {source} ---")
        result = manager.scrape_source(source, combined_kw, Config.TARGET_LOCATIONS)
        all_results[source] = result
        print(f"  Found: {result.get('total_found', 0)}, Matched: {result.get('matched_jobs', 0)}, New: {result.get('new_jobs', 0)}")

    # 2) LinkedIn with fewer keywords to avoid rate limiting
    linkedin_kw = ['Data Engineer', 'Data Analyst', 'Data Scientist', 'Machine Learning Engineer', 'Data Engineer Co-op']
    print(f"\n--- Scraping LinkedIn (5 keywords) ---")
    result = manager.scrape_source('linkedin', linkedin_kw, Config.LINKEDIN_LOCATIONS)
    all_results['linkedin'] = result
    print(f"  Found: {result.get('total_found', 0)}, Matched: {result.get('matched_jobs', 0)}, New: {result.get('new_jobs', 0)}")

    # Summary
    total_new = sum(r.get('new_jobs', 0) for r in all_results.values())
    total_matched = sum(r.get('matched_jobs', 0) for r in all_results.values())
    print(f"\n{'='*60}")
    print(f"TOTAL: {total_new} new jobs added, {total_matched} matched")
    print(f"{'='*60}")

    from backend.models import Job
    total_in_db = Job.query.filter(Job.is_hidden == False).count()
    print(f"Jobs in database: {total_in_db}")
