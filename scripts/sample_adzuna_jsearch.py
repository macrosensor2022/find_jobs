"""Sample Adzuna + JSearch run: counts, budgets, 3 example normalized rows.

Uses live APIs when keys are set; otherwise maps fixture JSON so you can
verify schema/market branching without burning quota.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from scrapers.adzuna_scraper import AdzunaScraper
from scrapers.jsearch_scraper import JSearchScraper

FIX = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tests', 'fixtures')


def _print_row(label, job):
    print(f'\n--- {label} ---')
    for k in (
        'title', 'company', 'location', 'market', 'source', 'job_url',
        'salary_min', 'salary_max', 'salary_predicted', 'description_partial',
        'external_id', 'date_posted',
    ):
        v = job.get(k)
        if k == 'date_posted' and v is not None:
            v = v.isoformat() if hasattr(v, 'isoformat') else v
        print(f'  {k}: {v}')
    desc = (job.get('description') or '')[:80]
    print(f'  description[:80]: {desc!r}')


def main():
    adz = AdzunaScraper()
    js = JSearchScraper()

    adzuna_jobs = []
    jsearch_jobs = []

    if adz.app_id and adz.app_key:
        print('Adzuna: live keys found — running budgeted scrape')
        adzuna_jobs = adz.scrape(keywords=Config.SEARCH_KEYWORDS[:3])
    else:
        print('Adzuna: no keys — mapping fixture')
        raw = json.load(open(os.path.join(FIX, 'adzuna_sample.json'), encoding='utf-8'))
        adzuna_jobs = [
            adz.parse_job_listing(raw['results'][0], market='US'),
            adz.parse_job_listing(raw['results'][1], market='IN'),
        ]
        adz.calls_used = 0

    if js.api_key:
        print('JSearch: live key found — running budgeted scrape')
        jsearch_jobs = js.scrape()
    else:
        print('JSearch: no key — mapping fixture')
        raw = json.load(open(os.path.join(FIX, 'jsearch_sample.json'), encoding='utf-8'))
        jsearch_jobs = [js.parse_job_listing(x) for x in raw['data']]
        js.calls_used = 0

    all_jobs = adzuna_jobs + jsearch_jobs
    by_source = {}
    by_market = {}
    for j in all_jobs:
        by_source[j.get('source')] = by_source.get(j.get('source'), 0) + 1
        by_market[j.get('market')] = by_market.get(j.get('market'), 0) + 1

    print('\n=== COUNTS ===')
    print(f'  by_source: {by_source}')
    print(f'  by_market: {by_market}')
    print(f'  Adzuna calls_used={adz.calls_used}/{adz.max_calls} (budget MAX_ADZUNA_CALLS)')
    print(f'  JSearch calls_used={js.calls_used}/{js.max_calls} (budget MAX_JSEARCH_CALLS)')

    us_adz = next((j for j in adzuna_jobs if j.get('market') == 'US'), None)
    in_adz = next((j for j in adzuna_jobs if j.get('market') == 'IN'), None)
    js_row = next((j for j in jsearch_jobs if j), None)

    if us_adz:
        _print_row('Adzuna-US example', us_adz)
    if in_adz:
        _print_row('Adzuna-IN example', in_adz)
    if js_row:
        _print_row('JSearch example', js_row)

    # Market-branch smoke (no DB required)
    from scrapers.job_scraper_manager import JobScraperManager
    from backend.models import Job
    from unittest.mock import MagicMock
    import scrapers.job_scraper_manager as jsm

    mgr = JobScraperManager(MagicMock(), min_match_score=20)
    jsm.lookup_employer = lambda c, s: {
        'is_everify': True, 'h1b_lca_count': 5, 'wage_level': 1,
        'employer_match_conf': 0.85, 'median_wage': None,
    }
    jsm.lookup_opportunity_score = lambda s, c: 42.0

    if us_adz:
        uj = Job(title=us_adz['title'], company=us_adz['company'],
                 location=us_adz['location'], description=us_adz.get('description'),
                 source='adzuna', match_score=50)
        mgr._enrich_job_with_opt_data(uj, us_adz)
        print(f"\nUS enrich: market={uj.market} is_everify={uj.is_everify} "
              f"loc_opp={uj.location_opportunity_score} rank={uj.rank_score}")
    if in_adz:
        ij = Job(title=in_adz['title'], company=in_adz['company'],
                 location=in_adz['location'], description=in_adz.get('description'),
                 source='adzuna', match_score=50)
        mgr._enrich_job_with_opt_data(ij, in_adz)
        print(f"IN enrich: market={ij.market} is_everify={ij.is_everify} "
              f"loc_opp={ij.location_opportunity_score} rank={ij.rank_score} "
              f"(sponsor/LCA/metro skipped)")


if __name__ == '__main__':
    main()
