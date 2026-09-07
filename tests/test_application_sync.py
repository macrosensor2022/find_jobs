"""Job.application_status is derived from Application, never written beside it.

Before this, the two only agreed on APPLIED: moving an application to
INTERVIEW or REJECTED left the job still reading "applied", and marking a job
applied from the Jobs page created no tracker entry at all.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import application_sync as sync  # noqa: E402


class FakeJob:
    def __init__(self, job_id=1):
        self.id = job_id
        self.company = 'Acme'
        self.title = 'Data Engineer'
        self.application_url = 'https://boards.io/acme/1'
        self.job_url = self.application_url
        self.application_status = 'not_applied'
        self.is_applied = False
        self.applied_date = None


class FakeApplication:
    rows = []

    def __init__(self, **kwargs):
        self.id = len(FakeApplication.rows) + 1
        self.job_id = kwargs.get('job_id')
        self.company = kwargs.get('company')
        self.role = kwargs.get('role')
        self.application_url = kwargs.get('application_url')
        self.status = kwargs.get('status', 'NEW')
        self.date_applied = kwargs.get('date_applied')
        self.job = kwargs.get('job')

    class _Query:
        def filter_by(self, **kwargs):
            self._kwargs = kwargs
            return self

        def first(self):
            for row in FakeApplication.rows:
                if all(getattr(row, k) == v for k, v in self._kwargs.items()):
                    return row
            return None

    query = _Query()


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)
        FakeApplication.rows.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass


class TestStatusMapping(unittest.TestCase):
    def test_every_application_status_maps_to_a_job_status(self):
        for status in sync.ALL_STATUSES:
            self.assertIn(sync.job_status_for(status), sync.JOB_STATUSES, status)

    def test_interview_stages_all_read_as_interviewing(self):
        for status in ('PHONE_SCREEN', 'INTERVIEW', 'TECHNICAL', 'FINAL'):
            self.assertEqual(sync.job_status_for(status), 'interviewing', status)

    def test_pre_application_states_are_not_applied(self):
        for status in ('NEW', 'SHORTLISTED', 'APPLYING'):
            self.assertEqual(sync.job_status_for(status), 'not_applied', status)
            self.assertFalse(sync.is_submitted(status), status)

    def test_offer_and_rejection_are_distinct(self):
        self.assertEqual(sync.job_status_for('OFFER'), 'offer')
        self.assertEqual(sync.job_status_for('REJECTED'), 'rejected')

    def test_round_trip_is_stable_for_the_coarse_states(self):
        for coarse in sync.JOB_STATUSES:
            fine = sync.application_status_for(coarse)
            self.assertEqual(sync.job_status_for(fine), coarse, coarse)

    def test_unknown_status_falls_back_safely(self):
        self.assertEqual(sync.job_status_for('NONSENSE'), 'not_applied')
        self.assertEqual(sync.application_status_for('nonsense'), 'NEW')
        self.assertEqual(sync.job_status_for(None), 'not_applied')


class TestSyncJobFromApplication(unittest.TestCase):
    def setUp(self):
        FakeApplication.rows = []

    def test_advancing_to_interview_updates_the_job(self):
        job = FakeJob()
        app = FakeApplication(job_id=1, status='APPLIED',
                              date_applied=datetime.now(timezone.utc), job=job)
        sync.sync_job_from_application(app, job)
        self.assertEqual(job.application_status, 'applied')

        app.status = 'INTERVIEW'
        sync.sync_job_from_application(app, job)
        self.assertEqual(job.application_status, 'interviewing')
        self.assertTrue(job.is_applied, 'interviewing still counts as applied')

    def test_rejection_propagates(self):
        job = FakeJob()
        app = FakeApplication(job_id=1, status='REJECTED', job=job)
        sync.sync_job_from_application(app, job)
        self.assertEqual(job.application_status, 'rejected')

    def test_withdrawing_before_sending_clears_applied(self):
        job = FakeJob()
        app = FakeApplication(job_id=1, status='WITHDRAWN', job=job)
        sync.sync_job_from_application(app, job)
        self.assertEqual(job.application_status, 'withdrawn')
        self.assertFalse(job.is_applied)

    def test_submitted_status_always_gets_a_date(self):
        job = FakeJob()
        app = FakeApplication(job_id=1, status='APPLIED', date_applied=None, job=job)
        sync.sync_job_from_application(app, job)
        self.assertIsNotNone(app.date_applied)
        self.assertEqual(job.applied_date, app.date_applied)

    def test_application_without_a_job_is_a_no_op(self):
        app = FakeApplication(job_id=None, status='APPLIED', job=None)
        self.assertIsNone(sync.sync_job_from_application(app))


class TestSyncApplicationFromJob(unittest.TestCase):
    def setUp(self):
        FakeApplication.rows = []
        self.session = FakeSession()

    def test_marking_a_job_applied_creates_the_tracker_entry(self):
        job = FakeJob()
        app = sync.sync_application_from_job(
            job, FakeApplication, self.session, status='applied')
        self.assertIsNotNone(app)
        self.assertEqual(app.status, 'APPLIED')
        self.assertIsNotNone(app.date_applied)
        self.assertTrue(job.is_applied)

    def test_not_applied_does_not_create_an_empty_tracker_row(self):
        job = FakeJob()
        app = sync.sync_application_from_job(
            job, FakeApplication, self.session, status='not_applied')
        self.assertIsNone(app)
        self.assertEqual(self.session.added, [])

    def test_existing_application_is_moved_not_duplicated(self):
        job = FakeJob()
        existing = FakeApplication(job_id=1, status='APPLIED', job=job)
        FakeApplication.rows.append(existing)

        app = sync.sync_application_from_job(
            job, FakeApplication, self.session, status='offer')
        self.assertIs(app, existing)
        self.assertEqual(app.status, 'OFFER')
        self.assertEqual(len(FakeApplication.rows), 1)

    def test_job_and_application_never_disagree_after_a_sync(self):
        job = FakeJob()
        for coarse in sync.JOB_STATUSES:
            app = sync.sync_application_from_job(
                job, FakeApplication, self.session, status=coarse)
            if app is None:
                self.assertEqual(job.application_status, 'not_applied')
                continue
            self.assertEqual(
                job.application_status, sync.job_status_for(app.status),
                f'{coarse}: job={job.application_status} app={app.status}',
            )


if __name__ == '__main__':
    unittest.main()
