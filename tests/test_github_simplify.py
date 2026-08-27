"""Unit tests for SimplifyJobs GitHub listing scraper (no network)."""

import unittest
from datetime import datetime, timezone

from scrapers.github_simplify_scraper import GithubNewGradScraper


SAMPLE = {
    "source": "Simplify",
    "category": "AI/ML/Data",
    "company_name": "Acme Analytics",
    "id": "test-de-001",
    "title": "Data Engineer New Grad",
    "active": True,
    "date_updated": int(datetime.now(timezone.utc).timestamp()),
    "date_posted": int(datetime.now(timezone.utc).timestamp()),
    "url": "https://example.com/jobs/de-new-grad",
    "locations": ["Boston, MA", "Remote"],
    "company_url": "https://simplify.jobs/c/Acme",
    "is_visible": True,
    "sponsorship": "Other",
    "degrees": ["Bachelor's"],
}


class TestGithubSimplify(unittest.TestCase):
    def setUp(self):
        self.scraper = GithubNewGradScraper()

    def test_parses_data_engineer_new_grad(self):
        job = self.scraper.parse_job_listing(SAMPLE)
        self.assertIsNotNone(job)
        self.assertEqual(job['title'], 'Data Engineer New Grad')
        self.assertEqual(job['company'], 'Acme Analytics')
        self.assertEqual(job['source'], 'github_newgrad')
        self.assertIn('Boston', job['location'])

    def test_drops_inactive(self):
        item = dict(SAMPLE, active=False)
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_drops_senior(self):
        item = dict(SAMPLE, title='Senior Data Engineer')
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_drops_excluded_west_coast(self):
        item = dict(SAMPLE, locations=['San Francisco, CA'])
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_keeps_west_coast_when_exclusion_cleared(self):
        self.scraper.excluded_states = []
        item = dict(SAMPLE, locations=['San Francisco, CA'])
        job = self.scraper.parse_job_listing(item)
        self.assertIsNotNone(job)
        self.assertIn('San Francisco', job['location'])

    def test_drops_unrelated_swe(self):
        item = dict(SAMPLE, category='Software', title='iOS Engineer New Grad')
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_drops_internship_title(self):
        item = dict(SAMPLE, title='Data Engineer Intern')
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_drops_coop_title(self):
        item = dict(SAMPLE, title='Data Engineer Co-op')
        self.assertIsNone(self.scraper.parse_job_listing(item))

    def test_marks_no_sponsorship(self):
        item = dict(SAMPLE, sponsorship='Does Not Offer Sponsorship')
        job = self.scraper.parse_job_listing(item)
        self.assertEqual(job.get('sponsorship_hint'), 'no_sponsorship')


if __name__ == '__main__':
    unittest.main()
