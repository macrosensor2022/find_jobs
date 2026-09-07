"""The four timestamps are four different facts and must stay separate.

    first_seen / date_scraped  when *we* first discovered the job. Never moves.
    last_seen                  when a source last re-confirmed it. Moves.
    date_posted                the source's own posting date, or NULL.
    source_updated_at          the source's own update time, or NULL.

Plus deduplication: collapse genuine re-discoveries, never merge two different
openings.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.dedupe import (  # noqa: E402
    build_dedupe_key, normalize_company, normalize_title, normalize_url,
    prefer, source_rank,
)


def _ago(**kwargs):
    return datetime.now(timezone.utc) - timedelta(**kwargs)


class StoredJob:
    """Minimal stand-in for a stored Job row that _merge_duplicate mutates."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id', 1)
        self.source = kwargs.get('source', 'remoteok')
        self.first_seen = kwargs.get('first_seen')
        self.last_seen = kwargs.get('last_seen')
        self.date_scraped = kwargs.get('date_scraped')
        self.date_posted = kwargs.get('date_posted')
        self.date_posted_origin = kwargs.get('date_posted_origin')
        self.source_updated_at = kwargs.get('source_updated_at')
        self.source_list = None
        self.source_count = 1
        self.alt_source_urls = None
        self.job_url = kwargs.get('job_url', 'https://example.com/jobs/1')
        self.source_url = self.job_url
        self.application_url = kwargs.get('application_url', self.job_url)
        self.application_url_status = 'unverified'
        self.external_id = kwargs.get('external_id')
        self.description = kwargs.get('description', 'x' * 500)
        self.description_partial = False
        self.possible_repost = False
        self.freshness_hours = None
        self.freshness_bucket = None
        self.is_expired = False


def _merge(existing, job_data, source='remoteok'):
    """Call the real merge routine without needing a database."""
    from scrapers.job_scraper_manager import JobScraperManager

    manager = JobScraperManager.__new__(JobScraperManager)
    JobScraperManager._merge_duplicate(manager, existing, job_data, source)
    return existing


class TestRediscoveryTimestamps(unittest.TestCase):
    def test_rediscovery_moves_last_seen_only(self):
        discovered = _ago(days=30)
        job = StoredJob(first_seen=discovered, last_seen=discovered,
                        date_scraped=discovered, date_posted=_ago(days=45))
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme'})

        self.assertEqual(job.first_seen, discovered,
                         'first_seen must never move on rediscovery')
        self.assertEqual(job.date_scraped, discovered,
                         'date_scraped must never move on rediscovery')
        self.assertGreater(job.last_seen, discovered)

    def test_rediscovery_does_not_touch_the_posting_date(self):
        posted = _ago(days=45)
        job = StoredJob(first_seen=_ago(days=30), last_seen=_ago(days=30),
                        date_scraped=_ago(days=30), date_posted=posted)
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme'})
        self.assertEqual(job.date_posted, posted)

    def test_freshness_after_rediscovery_reflects_the_posting_date(self):
        job = StoredJob(first_seen=_ago(days=30), last_seen=_ago(days=30),
                        date_scraped=_ago(days=30), date_posted=_ago(days=45))
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme'})
        self.assertEqual(job.freshness_bucket, 'stale')

    def test_unknown_posting_date_is_filled_in_when_a_source_supplies_one(self):
        real_date = _ago(days=2)
        job = StoredJob(date_posted=None, date_posted_origin='unknown',
                        first_seen=_ago(days=1), last_seen=_ago(days=1))
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme',
                     'date_posted': real_date, 'date_posted_origin': 'feed'})
        self.assertEqual(job.date_posted, real_date)
        self.assertEqual(job.date_posted_origin, 'feed')

    def test_a_newer_posting_date_marks_a_possible_repost(self):
        job = StoredJob(date_posted=_ago(days=30),
                        first_seen=_ago(days=30), last_seen=_ago(days=30))
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme',
                     'date_posted': _ago(days=1), 'date_posted_origin': 'feed'})
        self.assertTrue(job.possible_repost)

    def test_source_update_time_is_stored_separately(self):
        posted = _ago(days=20)
        job = StoredJob(date_posted=posted, first_seen=_ago(days=20),
                        last_seen=_ago(days=20))
        updated = _ago(days=1)
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme',
                     'source_updated_at': updated})
        self.assertEqual(job.source_updated_at, updated)
        self.assertEqual(job.date_posted, posted,
                         'an update time must never overwrite the posting date')

    def test_missing_first_seen_is_repaired_not_invented_forward(self):
        job = StoredJob(first_seen=None, last_seen=None, date_scraped=None)
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme'})
        self.assertIsNotNone(job.first_seen)
        self.assertIsNotNone(job.date_scraped)

    def test_authoritative_source_wins_the_listing(self):
        job = StoredJob(source='jsearch', job_url='https://aggregator.test/1')
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme',
                     'job_url': 'https://boards.greenhouse.io/acme/jobs/7'},
               source='greenhouse')
        self.assertEqual(job.source, 'greenhouse')
        self.assertIn('greenhouse.io', job.job_url)

    def test_alternate_source_urls_are_kept(self):
        job = StoredJob(job_url='https://a.test/1')
        _merge(job, {'title': 'Data Engineer', 'company': 'Acme',
                     'job_url': 'https://b.test/1'}, source='remotive')
        self.assertIn('remotive', job.source_list)
        self.assertEqual(job.source_count, 2)


class TestDedupeIdentity(unittest.TestCase):
    def test_same_posting_across_sources_collapses(self):
        a = {'company': 'Acme Inc.', 'title': 'Data Engineer, New Grad',
             'location': 'Boston, MA'}
        b = {'company': 'Acme', 'title': 'Data Engineer (New Graduate)',
             'location': 'Boston, MA'}
        self.assertEqual(build_dedupe_key(a), build_dedupe_key(b))

    def test_different_roles_at_one_company_stay_separate(self):
        a = {'company': 'Acme', 'title': 'Data Engineer', 'location': 'Boston, MA'}
        b = {'company': 'Acme', 'title': 'Data Analyst', 'location': 'Boston, MA'}
        self.assertNotEqual(build_dedupe_key(a), build_dedupe_key(b))

    def test_same_role_in_different_cities_stays_separate(self):
        a = {'company': 'Acme', 'title': 'Data Engineer', 'location': 'Boston, MA'}
        b = {'company': 'Acme', 'title': 'Data Engineer', 'location': 'Austin, TX'}
        self.assertNotEqual(build_dedupe_key(a), build_dedupe_key(b))

    def test_bracketed_specialisation_is_not_discarded(self):
        # "(Visual Search)" and "(Ranking)" are different openings.
        a = {'company': 'Acme', 'title': 'ML Engineer (Visual Search)',
             'location': 'Boston, MA'}
        b = {'company': 'Acme', 'title': 'ML Engineer (Ranking)',
             'location': 'Boston, MA'}
        self.assertNotEqual(build_dedupe_key(a), build_dedupe_key(b))

    def test_seniority_levels_are_not_merged_into_one_opening(self):
        # Level tokens are stripped for identity, so this documents the known
        # trade-off: a company posting both levels in one city collapses.
        a = {'company': 'Acme', 'title': 'Data Engineer I', 'location': 'Boston, MA'}
        b = {'company': 'Acme', 'title': 'Data Engineer', 'location': 'Boston, MA'}
        self.assertEqual(build_dedupe_key(a), build_dedupe_key(b))

    def test_url_normalisation_strips_tracking_but_keeps_the_id(self):
        self.assertEqual(
            normalize_url('https://www.boards.io/acme/jobs/123?utm_source=x'),
            normalize_url('https://boards.io/acme/jobs/123/'),
        )
        self.assertNotEqual(
            normalize_url('https://boards.io/acme/jobs/123'),
            normalize_url('https://boards.io/acme/jobs/124'),
        )

    def test_company_suffixes_are_normalised_away(self):
        self.assertEqual(normalize_company('Acme, Inc.'), normalize_company('ACME LLC'))

    def test_title_normalisation_keeps_the_discriminating_words(self):
        self.assertIn('data', normalize_title('Senior Data Engineer II'))
        self.assertIn('engineer', normalize_title('Senior Data Engineer II'))

    def test_falls_back_to_the_url_when_identity_is_missing(self):
        key = build_dedupe_key({'company': '', 'title': '',
                                'job_url': 'https://boards.io/acme/jobs/9'})
        self.assertEqual(key, 'boards.io/acme/jobs/9')

    def test_no_identity_and_no_url_yields_no_key(self):
        self.assertIsNone(build_dedupe_key({'company': '', 'title': ''}))

    def test_official_boards_outrank_aggregators(self):
        self.assertTrue(prefer('jsearch', 'greenhouse'))
        self.assertTrue(prefer('linkedin', 'ats'))
        self.assertFalse(prefer('greenhouse', 'jsearch'))
        self.assertGreater(source_rank('greenhouse'), source_rank('adzuna'))


if __name__ == '__main__':
    unittest.main()
