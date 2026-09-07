"""API contract tests — hermetic replacements for the old platform check.

``tests/test_platform.py`` claimed to cover these endpoints but talked to a
live server over HTTP and recorded failures in a counter instead of raising,
so every one of its checks reported green even when pointed at a dead port.

These use Flask's test client against an isolated database, so they assert for
real, need no running server, and cannot touch ``instance/jobs.db``.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402
from backend.models import Application, Job, db  # noqa: E402
from config.settings import Config  # noqa: E402


def _ago(**kwargs):
    return datetime.now(timezone.utc) - timedelta(**kwargs)


class ApiTestCase(unittest.TestCase):
    """Shared client + a couple of seeded jobs in the isolated test DB."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.ctx = app.app_context()
        cls.ctx.push()

        # Guard: never run against the real database, whatever the caller did.
        uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
        assert 'instance/jobs.db' not in uri.replace('\\', '/'), (
            f'refusing to run API tests against the production database: {uri}'
        )

        db.create_all()
        cls._seed()

    @classmethod
    def _seed(cls):
        if Job.query.filter_by(external_id='api-contract-1').first():
            return
        now = datetime.now(timezone.utc)
        job = Job(
            title='Data Engineer', company='Contract Test Co',
            location='Boston, MA', description='SQL, Python, ETL. ' * 40,
            job_url='https://example.test/jobs/1',
            application_url='https://example.test/jobs/1',
            application_url_status='verified',
            source='greenhouse', external_id='api-contract-1',
            date_posted=_ago(days=2), date_scraped=now,
            first_seen=now, last_seen=now,
            candidate_match_score=80, final_score=78.0, job_quality_score=90,
            opportunity_score=70, role_tier=2, is_hidden=False, is_applied=False,
            is_expired=False, is_not_interested=False,
            exp_hard_drop=False, location_blocked=False, role_blocked=False,
        )
        stale = Job(
            title='Data Analyst', company='Contract Test Co',
            location='Remote', description='Reporting and dashboards. ' * 40,
            job_url='https://example.test/jobs/2',
            application_url='https://example.test/jobs/2',
            application_url_status='unverified',
            source='remoteok', external_id='api-contract-2',
            date_posted=_ago(days=60), date_scraped=now,
            first_seen=now, last_seen=now,
            candidate_match_score=60, final_score=55.0, job_quality_score=80,
            opportunity_score=50, role_tier=1, is_hidden=False, is_applied=False,
            is_expired=False, is_not_interested=False,
            exp_hard_drop=False, location_blocked=False, role_blocked=False,
        )
        db.session.add_all([job, stale])
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    @staticmethod
    def seeded_job(external_id='api-contract-1'):
        """Look the fixture up by external_id.

        The isolated DB persists across test classes in one session, so _seed
        is a no-op after the first class and a cached row id would be unset.
        """
        job = Job.query.filter_by(external_id=external_id).first()
        assert job is not None, f'fixture {external_id} missing'
        return job

    def get_json(self, path, expect=200):
        response = self.client.get(path)
        self.assertEqual(response.status_code, expect, f'{path} -> {response.data[:200]}')
        return response.get_json()


class TestIsolation(ApiTestCase):
    def test_suite_is_not_pointed_at_the_production_database(self):
        uri = str(app.config['SQLALCHEMY_DATABASE_URI']).replace('\\', '/')
        self.assertNotIn('instance/jobs.db', uri)

    def test_testing_mode_is_detected(self):
        self.assertTrue(Config.TESTING_MODE or os.getenv('JOBTRACKER_TEST') == '1')


class TestReadEndpoints(ApiTestCase):
    def test_stats_shape(self):
        data = self.get_json('/api/stats')
        for key in ('total_jobs', 'applied_jobs', 'favorite_jobs',
                    'new_today', 'by_source', 'by_status'):
            self.assertIn(key, data)

    def test_jobs_list_shape_and_pagination(self):
        data = self.get_json('/api/jobs?per_page=5')
        for key in ('jobs', 'total', 'pages', 'current_page',
                    'has_next', 'has_prev'):
            self.assertIn(key, data)
        self.assertLessEqual(len(data['jobs']), 5)

    def test_per_page_is_clamped(self):
        data = self.get_json('/api/jobs?per_page=99999')
        from backend.app import MAX_PAGE_SIZE
        self.assertLessEqual(len(data['jobs']), MAX_PAGE_SIZE)

    def test_bad_pagination_params_do_not_500(self):
        for query in ('page=abc', 'per_page=abc', 'page=-5', 'per_page=0'):
            response = self.client.get(f'/api/jobs?{query}')
            self.assertEqual(response.status_code, 200, query)

    def test_jobs_filter_by_source(self):
        data = self.get_json('/api/jobs?per_page=50&source=greenhouse')
        for job in data['jobs']:
            self.assertEqual(job['source'], 'greenhouse')

    def test_jobs_search(self):
        data = self.get_json('/api/jobs?per_page=10&search=data')
        self.assertIn('jobs', data)

    def test_job_detail_and_404(self):
        job_id = self.seeded_job().id
        data = self.get_json(f'/api/jobs/{job_id}')
        self.assertEqual(data['id'], job_id)
        self.assertIn('freshness_bucket', data)
        self.get_json('/api/jobs/99999999', expect=404)

    def test_briefing_shape(self):
        data = self.get_json('/api/briefing?limit=5')
        for key in ('counts', 'top_jobs', 'thresholds', 'generated_at'):
            self.assertIn(key, data)

    def test_profile_shape(self):
        data = self.get_json('/api/profile')
        for key in ('name', 'education', 'experience'):
            self.assertIn(key, data)

    def test_config_endpoints_return_non_empty_lists(self):
        locations = self.get_json('/api/config/locations')
        keywords = self.get_json('/api/config/keywords')
        self.assertIsInstance(locations, list)
        self.assertIsInstance(keywords, list)
        self.assertTrue(locations and keywords)

    def test_source_metrics_reports_every_registered_source(self):
        data = self.get_json('/api/sources/metrics')
        names = {s['source'] for s in data['sources']}
        self.assertEqual(names, set(Config.SOURCE_REGISTRY))
        self.assertIn('configuration', data)

    def test_search_health(self):
        self.assertIn('status', self.get_json('/api/search/health'))

    def test_followups_buckets(self):
        data = self.get_json('/api/followups')
        for key in ('overdue', 'due_today', 'upcoming', 'counts'):
            self.assertIn(key, data)


class TestErrorContract(ApiTestCase):
    def test_unknown_api_route_returns_json_404(self):
        response = self.client.get('/api/definitely-not-a-route')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['error'], 'Not found')

    def test_wrong_method_returns_json_405(self):
        response = self.client.delete('/api/briefing')
        self.assertEqual(response.status_code, 405)
        self.assertIn('not allowed', response.get_json()['error'])

    def test_malformed_json_body_returns_json_400(self):
        response = self.client.post(
            '/api/applications', data='{not json',
            content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.get_json())

    def test_errors_never_leak_a_traceback(self):
        response = self.client.get('/api/definitely-not-a-route')
        body = response.get_data(as_text=True)
        for leak in ('Traceback', 'File "', 'sqlalchemy', 'D:\\\\find_jobs'):
            self.assertNotIn(leak, body)


class TestApplicationWorkflow(ApiTestCase):
    """The workflow, driven through the API rather than against a live server.

    Each test creates its own job + application so the class has no ordering
    dependency (unittest runs methods alphabetically, which is not the order
    a workflow reads in).
    """

    _counter = 0

    def _fresh_job(self):
        """A throwaway job, so one test's application cannot affect another."""
        TestApplicationWorkflow._counter += 1
        marker = f'api-contract-wf-{TestApplicationWorkflow._counter}'
        now = datetime.now(timezone.utc)
        job = Job(
            title='Data Engineer', company='Workflow Test Co',
            location='Boston, MA', description='SQL and pipelines. ' * 40,
            job_url=f'https://example.test/wf/{marker}',
            application_url=f'https://example.test/wf/{marker}',
            application_url_status='verified',
            source='greenhouse', external_id=marker,
            date_posted=_ago(days=1), date_scraped=now,
            first_seen=now, last_seen=now,
            candidate_match_score=80, final_score=78.0, job_quality_score=90,
            opportunity_score=70, role_tier=2, is_hidden=False, is_applied=False,
            is_expired=False, is_not_interested=False,
            exp_hard_drop=False, location_blocked=False, role_blocked=False,
        )
        db.session.add(job)
        db.session.commit()
        return job

    def _application_for(self, job, status='SHORTLISTED'):
        response = self.client.post(
            '/api/applications', json={'job_id': job.id, 'status': status})
        self.assertIn(response.status_code, (200, 201))
        return response.get_json()['id']

    def test_create_requires_a_job_id(self):
        response = self.client.post('/api/applications', json={})
        self.assertEqual(response.status_code, 400)

    def test_create_rejects_an_unknown_job(self):
        response = self.client.post('/api/applications', json={'job_id': 99999999})
        self.assertEqual(response.status_code, 404)

    def test_status_transitions_keep_the_job_in_step(self):
        job = self._fresh_job()
        app_id = self._application_for(job)

        # The regression this guards: the job used to stay at "applied" while
        # the application advanced to INTERVIEW or OFFER.
        expected = [
            ('SHORTLISTED', 'not_applied', False),
            ('APPLIED', 'applied', True),
            ('INTERVIEW', 'interviewing', True),
            ('OFFER', 'offer', True),
        ]
        for status, coarse, applied in expected:
            response = self.client.put(
                f'/api/applications/{app_id}', json={'status': status})
            self.assertEqual(response.status_code, 200, status)
            db.session.expire_all()
            refreshed = db.session.get(Job, job.id)
            self.assertEqual(refreshed.application_status, coarse, status)
            self.assertEqual(bool(refreshed.is_applied), applied, status)

    def test_marking_a_job_applied_creates_the_tracker_entry(self):
        job = self._fresh_job()
        response = self.client.put(
            f'/api/jobs/{job.id}', json={'application_status': 'applied'})
        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        application = Application.query.filter_by(job_id=job.id).first()
        self.assertIsNotNone(application, 'job-side edit must create the application')
        self.assertEqual(application.status, 'APPLIED')
        self.assertIsNotNone(application.next_followup_date,
                             'a follow-up must be scheduled on this path too')

    def test_invalid_job_status_is_rejected(self):
        job = self._fresh_job()
        response = self.client.put(
            f'/api/jobs/{job.id}', json={'application_status': 'nonsense'})
        self.assertEqual(response.status_code, 400)

    def test_invalid_application_status_is_rejected(self):
        job = self._fresh_job()
        app_id = self._application_for(job)
        response = self.client.put(
            f'/api/applications/{app_id}', json={'status': 'NONSENSE'})
        self.assertEqual(response.status_code, 400)

    def test_followup_actions(self):
        job = self._fresh_job()
        app_id = self._application_for(job, status='APPLIED')
        self.assertEqual(self.client.post(
            f'/api/applications/{app_id}/followup',
            json={'action': 'snoozed', 'days': 5}).status_code, 200)
        self.assertEqual(self.client.post(
            f'/api/applications/{app_id}/followup',
            json={'action': 'explode'}).status_code, 400)
        self.assertEqual(self.client.post(
            f'/api/applications/{app_id}/followup',
            json={'action': 'cancelled'}).status_code, 200)
        db.session.expire_all()
        self.assertIsNone(db.session.get(Application, app_id).next_followup_date)

    def test_snooze_rejects_an_out_of_range_delay(self):
        job = self._fresh_job()
        app_id = self._application_for(job, status='APPLIED')
        for days in (0, 900, 'soon'):
            response = self.client.post(
                f'/api/applications/{app_id}/followup',
                json={'action': 'snoozed', 'days': days})
            self.assertEqual(response.status_code, 400, days)


class TestScrapeEndpointContract(ApiTestCase):
    """The scrape endpoint's guards, without ever starting a scrape.

    The old platform check POSTed a real scrape here; that is what wrote into
    the production database. These assert the contract only.
    """

    def test_status_endpoint_shape(self):
        data = self.get_json('/api/scrape/status')
        for key in ('status', 'message', 'progress'):
            self.assertIn(key, data)

    def test_disabled_sources_are_reported_not_silently_skipped(self):
        from services import source_health
        status = source_health.source_status('adzuna')
        if not status['enabled']:
            self.assertTrue(status['reason'])
            self.assertNotEqual(status['reason'], '')


if __name__ == '__main__':
    unittest.main()
