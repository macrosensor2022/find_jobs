"""Freshness must be a function of *now* and the source posting date.

These cover the bug class the product cared about most: a job posted weeks ago
that was rediscovered today must never present as new, must never be counted as
new, and must never win the Today ranking on its rediscovery.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config  # noqa: E402
from services.freshness import bucket_for, evaluate, is_expired  # noqa: E402
from services.maintenance import age_cutoff, live_freshness  # noqa: E402


def _ago(**kwargs):
    return datetime.now(timezone.utc) - timedelta(**kwargs)


class FakeJob:
    """The subset of Job that the ranking and freshness code reads."""

    def __init__(self, **kwargs):
        self.final_score = kwargs.get('final_score', 50.0)
        self.date_posted = kwargs.get('date_posted')
        self.date_scraped = kwargs.get('date_scraped')
        self.first_seen = kwargs.get('first_seen')
        self.last_seen = kwargs.get('last_seen')
        self.role_tier = kwargs.get('role_tier', 1)
        self.application_recommendation = kwargs.get('application_recommendation')
        self.application_url_status = kwargs.get('application_url_status', 'unverified')
        self.freshness_bucket = kwargs.get('freshness_bucket')

    def live_freshness(self, now=None):
        return live_freshness(self.date_posted, now=now)


class TestLiveFreshness(unittest.TestCase):
    def test_bucket_tracks_actual_age(self):
        cases = [
            (_ago(hours=2), 'hot'),
            (_ago(hours=12), 'fresh'),
            (_ago(days=2), 'recent'),
            (_ago(days=5), 'aging'),
            (_ago(days=10), 'old'),
            (_ago(days=40), 'stale'),
        ]
        for posted, expected in cases:
            hours, bucket = live_freshness(posted)
            self.assertEqual(bucket, expected, f'{posted} -> {bucket}')
            self.assertIsNotNone(hours)

    def test_unknown_posting_date_stays_unknown(self):
        hours, bucket = live_freshness(None)
        self.assertIsNone(hours)
        self.assertIsNone(bucket)
        self.assertEqual(bucket_for(None), 'unknown')

    def test_unknown_date_is_never_auto_expired(self):
        # An absent posting date is not evidence that a posting is old.
        self.assertFalse(is_expired(None))

    def test_stale_stored_bucket_does_not_win_over_real_age(self):
        # The exact regression: a row scored two weeks ago still carries
        # freshness_bucket='fresh'. The live value must disagree with it.
        job = FakeJob(date_posted=_ago(days=14, hours=2), freshness_bucket='fresh')
        _, bucket = job.live_freshness()
        self.assertEqual(bucket, 'stale')
        self.assertNotEqual(bucket, job.freshness_bucket)

    def test_future_posting_date_reads_as_brand_new(self):
        # Timezone skew at the source must not produce a negative age.
        hours, bucket = live_freshness(datetime.now(timezone.utc) + timedelta(hours=3))
        self.assertEqual(hours, 0)
        self.assertEqual(bucket, 'hot')

    def test_naive_datetimes_are_treated_as_utc(self):
        naive = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
        hours, bucket = live_freshness(naive)
        self.assertEqual(bucket, 'hot')
        self.assertLessEqual(hours, 3)


class TestScrapeTimeIsNotPostingTime(unittest.TestCase):
    def test_rediscovered_stale_job_is_still_stale(self):
        """Rediscovered today, posted 45 days ago -> stale, not fresh."""
        job = FakeJob(
            date_posted=_ago(days=45),
            first_seen=_ago(days=45),
            last_seen=datetime.now(timezone.utc),
            date_scraped=_ago(days=45),
        )
        _, bucket = job.live_freshness()
        self.assertEqual(bucket, 'stale')

    def test_freshness_ignores_discovery_timestamps_entirely(self):
        """Same posting date, opposite discovery history -> same freshness."""
        posted = _ago(days=20)
        just_found = FakeJob(date_posted=posted, first_seen=datetime.now(timezone.utc))
        long_known = FakeJob(date_posted=posted, first_seen=_ago(days=20))
        self.assertEqual(
            just_found.live_freshness()[1], long_known.live_freshness()[1]
        )

    def test_evaluate_reports_unknown_rather_than_guessing(self):
        result = evaluate(None)
        self.assertFalse(result['is_known'])
        self.assertEqual(result['bucket'], 'unknown')


class TestTodayRanking(unittest.TestCase):
    """Fresh + relevant must beat stale + high-scoring."""

    def _rank(self, job, now=None):
        from services.briefing import today_rank_score
        return today_rank_score(job, now=now)

    def test_fresh_relevant_job_beats_stale_high_scorer(self):
        stale_star = FakeJob(
            final_score=95.0, date_posted=_ago(days=40), role_tier=1,
            first_seen=_ago(days=40), last_seen=datetime.now(timezone.utc),
        )
        fresh_good = FakeJob(
            final_score=90.0, date_posted=_ago(hours=20), role_tier=1,
            first_seen=_ago(hours=20), last_seen=_ago(hours=20),
        )
        self.assertGreater(self._rank(fresh_good), self._rank(stale_star))

    def test_rediscovery_does_not_lift_a_stale_job(self):
        posted = _ago(days=40)
        never_reseen = FakeJob(final_score=80.0, date_posted=posted,
                               first_seen=posted, last_seen=posted)
        reseen_today = FakeJob(final_score=80.0, date_posted=posted,
                               first_seen=posted,
                               last_seen=datetime.now(timezone.utc))
        # Rediscovery is evidence the job is still open, not that it is new,
        # so it must not change where the job ranks today.
        self.assertEqual(self._rank(never_reseen), self._rank(reseen_today))

    def test_newly_discovered_job_gets_a_bounded_nudge(self):
        posted = _ago(days=3)
        old_find = FakeJob(final_score=70.0, date_posted=posted, first_seen=posted)
        new_find = FakeJob(final_score=70.0, date_posted=posted,
                           first_seen=datetime.now(timezone.utc))
        delta = self._rank(new_find) - self._rank(old_find)
        self.assertGreater(delta, 0)
        # Small enough that it cannot rescue a much worse job.
        self.assertLess(delta, 10)

    def test_dead_apply_link_sinks_a_job(self):
        live = FakeJob(final_score=70.0, date_posted=_ago(days=1),
                       application_url_status='verified')
        dead = FakeJob(final_score=70.0, date_posted=_ago(days=1),
                       application_url_status='dead')
        self.assertGreater(self._rank(live), self._rank(dead))

    def test_tier_one_outranks_unclassified_at_equal_score(self):
        tier1 = FakeJob(final_score=70.0, date_posted=_ago(days=1), role_tier=1)
        untiered = FakeJob(final_score=70.0, date_posted=_ago(days=1), role_tier=None)
        self.assertGreater(self._rank(tier1), self._rank(untiered))


class TestAgePolicy(unittest.TestCase):
    def test_policy_values_are_ordered_and_sane(self):
        self.assertGreater(Config.MAX_JOB_AGE_DAYS, Config.TODAY_MAX_AGE_DAYS)
        self.assertGreaterEqual(Config.WATCH_MAX_AGE_DAYS, Config.TODAY_MAX_AGE_DAYS)
        self.assertEqual(Config.JOB_EXPIRY_DAYS, Config.MAX_JOB_AGE_DAYS)

    def test_expiry_uses_posting_date(self):
        self.assertTrue(is_expired(_ago(days=Config.MAX_JOB_AGE_DAYS + 5)))
        self.assertFalse(is_expired(_ago(days=Config.MAX_JOB_AGE_DAYS - 5)))

    def test_age_cutoff_is_in_the_past(self):
        cutoff = age_cutoff(Config.TODAY_MAX_AGE_DAYS)
        self.assertLess(cutoff, datetime.now(timezone.utc))


if __name__ == '__main__':
    unittest.main()
