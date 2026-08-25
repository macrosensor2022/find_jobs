"""Adzuna / JSearch mapping, market branch, predicted-salary flag."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return json.load(f)


class TestAdzunaMapping(unittest.TestCase):
    def setUp(self):
        from scrapers.adzuna_scraper import AdzunaScraper
        self.scraper = AdzunaScraper()
        self.payload = _load('adzuna_sample.json')

    def test_us_row_maps_schema(self):
        raw = self.payload['results'][0]
        job = self.scraper.parse_job_listing(raw, market='US')
        self.assertEqual(job['title'], 'Data Engineer (New Grad)')
        self.assertEqual(job['company'], 'Acme Analytics')
        self.assertIn('Boston', job['location'])
        self.assertEqual(job['job_url'], 'https://www.adzuna.com/details/us-1001')
        self.assertEqual(job['market'], 'US')
        self.assertTrue(job['description_partial'])
        self.assertTrue(job['salary_predicted'])
        self.assertEqual(job['salary_min'], 85000)
        self.assertTrue(job['external_id'].startswith('adzuna-us-'))
        self.assertIsNotNone(job['date_posted'])

    def test_in_row_maps_schema(self):
        raw = self.payload['results'][1]
        job = self.scraper.parse_job_listing(raw, market='IN')
        self.assertEqual(job['market'], 'IN')
        self.assertEqual(job['company'], 'Infosys')
        self.assertIn('Bengaluru', job['location'])
        self.assertFalse(job['salary_predicted'])
        self.assertTrue(job['description_partial'])

    def test_missing_keys_skip(self):
        from scrapers.adzuna_scraper import AdzunaScraper
        s = AdzunaScraper()
        s.app_id = ''
        s.app_key = ''
        self.assertEqual(s.scrape(keywords=['Data Engineer']), [])


class TestJSearchMapping(unittest.TestCase):
    def setUp(self):
        from scrapers.jsearch_scraper import JSearchScraper
        self.scraper = JSearchScraper()
        self.payload = _load('jsearch_sample.json')

    def test_us_row(self):
        job = self.scraper.parse_job_listing(self.payload['data'][0])
        self.assertEqual(job['title'], 'Junior Data Engineer')
        self.assertEqual(job['company'], 'ZipRecruiter Mirror Co')
        self.assertEqual(job['market'], 'US')
        self.assertIn('Austin', job['location'])
        self.assertEqual(job['salary_min'], 90000)
        self.assertTrue(job['external_id'].startswith('jsearch-'))

    def test_in_row(self):
        job = self.scraper.parse_job_listing(self.payload['data'][1])
        self.assertEqual(job['market'], 'IN')
        self.assertIn('Hyderabad', job['location'])

    def test_missing_key_skip(self):
        from scrapers.jsearch_scraper import JSearchScraper
        s = JSearchScraper()
        s.api_key = ''
        self.assertEqual(s.scrape(), [])


class TestMarketBranch(unittest.TestCase):
    def test_us_gets_sponsor_fields_in_gets_neutral(self):
        from scrapers.job_scraper_manager import JobScraperManager
        from backend.models import Job

        session = MagicMock()
        mgr = JobScraperManager(session, min_match_score=20)

        # Stub lookup_employer path by patching method internals via job_data
        us_job = Job(
            title='Data Engineer New Grad',
            company='Acme',
            location='Boston, MA',
            description='Python SQL ETL entry level',
            source='adzuna',
            match_score=60,
        )
        in_job = Job(
            title='Data Engineer Intern',
            company='TCS',
            location='Hyderabad, India',
            description='Python SQL internship',
            source='jsearch',
            match_score=55,
        )

        # Patch lookup to avoid DB
        import scrapers.job_scraper_manager as jsm
        original = jsm.lookup_employer
        jsm.lookup_employer = lambda company, sess: {
            'is_everify': True,
            'h1b_lca_count': 10,
            'wage_level': 1,
            'employer_match_conf': 0.9,
            'median_wage': None,
        }
        try:
            jsm.lookup_opportunity_score = lambda sess, code: 40.0
            mgr._enrich_job_with_opt_data(us_job, {'market': 'US'})
            mgr._enrich_job_with_opt_data(in_job, {'market': 'IN'})
        finally:
            jsm.lookup_employer = original

        self.assertEqual(us_job.market, 'US')
        self.assertTrue(us_job.is_everify)
        self.assertIsNotNone(us_job.employer_match_conf)

        self.assertEqual(in_job.market, 'IN')
        self.assertIsNone(in_job.is_everify)
        self.assertIsNone(in_job.h1b_lca_count)
        self.assertIsNone(in_job.location_opportunity_score)
        # IN not penalized — rank_score still set from match + recency
        self.assertIsNotNone(in_job.rank_score)


if __name__ == '__main__':
    unittest.main()
