"""Apply is enabled only for a link we actually fetched and read.

Anything else — a login wall, a rate limit, a timeout, a redirect away from the
posting — is reported as what it is. None of those states may enable Apply, and
none of them may claim the job is fake.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from backend.models import _apply_detail, _apply_label  # noqa: E402
from services import verification  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, text='', url=None):
        self.status_code = status_code
        self.text = text
        self.url = url


class FakeHttp:
    """Stands in for `requests`, so no test touches the network."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._raises:
            raise self._raises
        return self._response


URL = 'https://boards.greenhouse.io/acme/jobs/12345'


class TestVerifyUrl(unittest.TestCase):
    def _verify(self, response=None, raises=None, url=URL):
        return verification.verify_url(url, session=FakeHttp(response, raises))

    def test_live_page_is_verified(self):
        result = self._verify(FakeResponse(200, 'Apply for this role', url=URL))
        self.assertEqual(result['url_status'], 'verified')
        self.assertEqual(result['verification_status'], 'active')

    def test_404_is_dead(self):
        result = self._verify(FakeResponse(404, 'Not found', url=URL))
        self.assertEqual(result['url_status'], 'dead')

    def test_410_is_dead(self):
        self.assertEqual(self._verify(FakeResponse(410, '', url=URL))['url_status'],
                         'dead')

    def test_closure_notice_in_body_is_dead(self):
        body = 'We are no longer accepting applications for this position.'
        result = self._verify(FakeResponse(200, body, url=URL))
        self.assertEqual(result['url_status'], 'dead')
        self.assertIn('no longer accepting', result['detail'])

    def test_403_is_blocked_not_dead(self):
        # A login wall is not evidence the job closed.
        result = self._verify(FakeResponse(403, '', url=URL))
        self.assertEqual(result['url_status'], 'blocked')
        self.assertNotEqual(result['url_status'], 'dead')

    def test_429_is_blocked(self):
        self.assertEqual(self._verify(FakeResponse(429, '', url=URL))['url_status'],
                         'blocked')

    def test_timeout_is_unverified_not_dead(self):
        result = self._verify(raises=requests.exceptions.Timeout('timed out'))
        self.assertEqual(result['url_status'], 'unverified')
        self.assertEqual(result['verification_status'], 'unreachable')

    def test_server_error_is_unverified(self):
        self.assertEqual(self._verify(FakeResponse(503, '', url=URL))['url_status'],
                         'unverified')

    def test_redirect_to_another_host_is_flagged(self):
        result = self._verify(
            FakeResponse(200, 'careers', url='https://other-site.com/careers')
        )
        self.assertEqual(result['url_status'], 'redirected')

    def test_redirect_to_a_generic_landing_page_is_flagged(self):
        result = self._verify(
            FakeResponse(200, 'all jobs', url='https://boards.greenhouse.io/jobs')
        )
        self.assertEqual(result['url_status'], 'redirected')

    def test_harmless_redirect_still_verifies(self):
        # Same posting, http->https or a trailing-slash bounce.
        result = self._verify(FakeResponse(200, 'Apply', url=URL + '/'))
        self.assertEqual(result['url_status'], 'verified')

    def test_missing_url_is_unknown(self):
        result = verification.verify_url('')
        self.assertEqual(result['url_status'], 'unknown')
        self.assertIsNone(result['http_status'])


class TestApplyGate(unittest.TestCase):
    def test_only_verified_is_applyable(self):
        self.assertEqual(verification.APPLYABLE_STATUSES, {'verified'})

    def test_labels_never_enable_apply_for_unverified_states(self):
        for status in ('unknown', 'unverified', 'blocked', 'redirected', 'dead'):
            self.assertNotEqual(_apply_label(URL, status), 'Apply now', status)

    def test_verified_reads_as_apply_now(self):
        self.assertEqual(_apply_label(URL, 'verified'), 'Apply now')

    def test_no_url_says_so_plainly(self):
        self.assertEqual(_apply_label(None, 'verified'), 'No apply link')

    def test_blocked_does_not_claim_the_job_is_fake(self):
        detail = _apply_detail(URL, 'blocked').lower()
        self.assertNotIn('fake', detail)
        self.assertIn('may still be open', detail)

    def test_every_status_has_an_explanation(self):
        for status in ('verified', 'dead', 'blocked', 'redirected',
                       'unverified', 'unknown'):
            self.assertTrue(_apply_detail(URL, status))


class TestApplyVerification(unittest.TestCase):
    class Job:
        application_url_status = None
        verification_status = None
        application_url_checked_at = None
        last_verified_at = None
        is_expired = False

    def test_dead_result_marks_the_job_expired(self):
        job = self.Job()
        verification.apply_verification(job, verification.verify_url(
            URL, session=FakeHttp(FakeResponse(404, '', url=URL))))
        self.assertTrue(job.is_expired)
        self.assertEqual(job.application_url_status, 'dead')

    def test_blocked_result_does_not_expire_the_job(self):
        job = self.Job()
        verification.apply_verification(job, verification.verify_url(
            URL, session=FakeHttp(FakeResponse(403, '', url=URL))))
        self.assertFalse(job.is_expired)
        self.assertEqual(job.application_url_status, 'blocked')

    def test_verification_stamps_a_checked_time(self):
        job = self.Job()
        verification.apply_verification(job, verification.verify_url(
            URL, session=FakeHttp(FakeResponse(200, 'Apply', url=URL))))
        self.assertIsNotNone(job.last_verified_at)
        self.assertIsNotNone(job.application_url_checked_at)


if __name__ == '__main__':
    unittest.main()
