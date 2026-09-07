"""A source that cannot run must say so.

The failure this guards against is quiet: Adzuna and JSearch have no API keys
configured, so they returned zero jobs and were recorded as
``status='success', jobs_discovered=0`` — indistinguishable from a board that
ran fine and genuinely had nothing.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config  # noqa: E402
from services import source_health  # noqa: E402


class TestSourceEnablement(unittest.TestCase):
    def setUp(self):
        self._saved = {}

    def tearDown(self):
        for key, value in self._saved.items():
            setattr(Config, key, value)

    def _set(self, key, value):
        self._saved.setdefault(key, getattr(Config, key, None))
        setattr(Config, key, value)

    def test_free_source_with_no_credentials_is_enabled(self):
        status = source_health.source_status('github_newgrad')
        self.assertTrue(status['enabled'])
        self.assertIsNone(status['reason'])

    def test_missing_api_key_disables_with_a_reason(self):
        self._set('ADZUNA_APP_ID', '')
        self._set('ADZUNA_APP_KEY', '')
        status = source_health.source_status('adzuna')
        self.assertFalse(status['enabled'])
        self.assertIn('credentials', status['reason'].lower())
        self.assertIn('ADZUNA_APP_ID', status['missing'])
        self.assertIn('ADZUNA_APP_KEY', status['missing'])

    def test_reason_names_the_key_but_never_its_value(self):
        self._set('JSEARCH_API_KEY', '')
        status = source_health.source_status('jsearch')
        self.assertIn('JSEARCH_API_KEY', status['reason'])

        self._set('JSEARCH_API_KEY', 'super-secret-value')
        enabled = source_health.source_status('jsearch')
        self.assertTrue(enabled['enabled'])
        # Nothing in the payload may carry the secret itself.
        self.assertNotIn('super-secret-value', repr(enabled))

    def test_partial_credentials_still_disable(self):
        self._set('ADZUNA_APP_ID', 'present')
        self._set('ADZUNA_APP_KEY', '')
        status = source_health.source_status('adzuna')
        self.assertFalse(status['enabled'])
        self.assertEqual(status['missing'], ['ADZUNA_APP_KEY'])

    def test_whitespace_only_credential_counts_as_missing(self):
        self._set('JSEARCH_API_KEY', '   ')
        self.assertFalse(source_health.is_enabled('jsearch'))

    def test_switched_off_source_reports_its_flag(self):
        self._set('ENABLE_REMOTEOK', False)
        status = source_health.source_status('remoteok')
        self.assertFalse(status['enabled'])
        self.assertIn('ENABLE_REMOTEOK', status['reason'])

    def test_unknown_source_is_not_silently_blocked(self):
        status = source_health.source_status('some_new_board')
        self.assertTrue(status['enabled'])
        self.assertFalse(status['registered'])

    def test_enabled_sources_splits_runnable_from_skipped(self):
        self._set('ADZUNA_APP_ID', '')
        self._set('ADZUNA_APP_KEY', '')
        runnable, skipped = source_health.enabled_sources(
            ['github_newgrad', 'adzuna', 'remoteok']
        )
        self.assertEqual(runnable, ['github_newgrad', 'remoteok'])
        self.assertEqual([s['source'] for s in skipped], ['adzuna'])

    def test_every_registered_source_is_reported(self):
        names = {s['source'] for s in source_health.configured_sources()}
        self.assertEqual(names, set(Config.SOURCE_REGISTRY))


class TestHealthLabels(unittest.TestCase):
    def test_disabled_and_failed_are_distinct_from_empty(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(
            source_health.health_label(source_health.STATUS_DISABLED, 0, None, now),
            'Disabled')
        self.assertEqual(
            source_health.health_label(source_health.STATUS_FAILED, 0, None, now),
            'Failing')

    def test_recent_empty_run_is_still_healthy(self):
        now = datetime.now(timezone.utc)
        label = source_health.health_label(
            source_health.STATUS_EMPTY, 0, now - timedelta(hours=2), now,
        )
        self.assertEqual(label, 'Healthy')

    def test_long_silent_source_is_flagged(self):
        now = datetime.now(timezone.utc)
        label = source_health.health_label(
            source_health.STATUS_EMPTY, 0, now - timedelta(days=30), now,
        )
        self.assertEqual(label, 'No results')

    def test_source_that_returned_jobs_is_healthy(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(
            source_health.health_label(source_health.STATUS_SUCCESS, 42, now, now),
            'Healthy')


class TestManagerSkipsDisabledSources(unittest.TestCase):
    """The manager must not even construct a run for a source it cannot use."""

    def test_disabled_source_result_is_labelled_disabled(self):
        from scrapers.job_scraper_manager import JobScraperManager

        started = datetime.now(timezone.utc)
        result = JobScraperManager._empty_source_result(
            'adzuna', started,
            run_status=source_health.STATUS_DISABLED,
            message='API credentials not configured',
        )
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['total_found'], 0)
        self.assertEqual(result['new_jobs'], 0)
        self.assertIn('credentials', result['message'])
        # A disabled source must never look like a clean success.
        self.assertNotEqual(result['status'], source_health.STATUS_SUCCESS)

    def test_failed_source_carries_the_error(self):
        from scrapers.job_scraper_manager import JobScraperManager

        result = JobScraperManager._empty_source_result(
            'nope', datetime.now(timezone.utc),
            run_status=source_health.STATUS_FAILED,
            message='Unknown source: nope', error='Unknown source: nope',
        )
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'], ['Unknown source: nope'])


class TestFullFeedKeywordFilter(unittest.TestCase):
    """Full-feed boards are fetched once and filtered locally."""

    def _filter(self, jobs, keywords):
        from scrapers.job_scraper_manager import JobScraperManager
        return JobScraperManager._filter_by_keywords(jobs, keywords)

    def test_keeps_matching_titles(self):
        jobs = [
            {'title': 'Data Engineer', 'job_url': 'a'},
            {'title': 'Chef de Partie', 'job_url': 'b'},
        ]
        kept = self._filter(jobs, ['Data Engineer'])
        self.assertEqual([j['title'] for j in kept], ['Data Engineer'])

    def test_matches_on_description_too(self):
        jobs = [{'title': 'Operations Analyst', 'description': 'Own our ETL pipelines',
                 'job_url': 'a'}]
        self.assertEqual(len(self._filter(jobs, ['ETL Developer'])), 1)

    def test_no_keywords_passes_everything_through(self):
        jobs = [{'title': 'Anything', 'job_url': 'a'}]
        self.assertEqual(len(self._filter(jobs, [])), 1)
        self.assertEqual(len(self._filter(jobs, None)), 1)

    def test_duplicate_urls_collapse(self):
        jobs = [
            {'title': 'Data Engineer', 'job_url': 'same'},
            {'title': 'Data Engineer', 'job_url': 'same'},
        ]
        self.assertEqual(len(self._filter(jobs, ['Data Engineer'])), 1)

    def test_short_tokens_do_not_match_everything(self):
        # "BI" is 2 chars and must not be used as a match token, or every
        # posting containing "bi" anywhere would pass.
        jobs = [{'title': 'Ambitious Chef', 'job_url': 'a'}]
        self.assertEqual(self._filter(jobs, ['BI']), jobs)

    def test_malformed_entries_are_dropped(self):
        jobs = [None, 'not a dict', {'title': 'Data Engineer', 'job_url': 'a'}]
        kept = self._filter(jobs, ['Data Engineer'])
        self.assertEqual(len(kept), 1)


if __name__ == '__main__':
    unittest.main()
