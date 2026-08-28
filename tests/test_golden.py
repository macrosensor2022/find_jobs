"""Tests for the V3 golden opportunity score (services/golden.py).

The golden score is a SIBLING composite — it must move with fit but never let a
single sub-signal (especially contact availability) dominate.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.golden import golden_opportunity_score


class TestGoldenOpportunity(unittest.TestCase):
    def test_bounded_0_100(self):
        for kw in ({}, {'contact_relevance_score': 99}):
            s = golden_opportunity_score(
                match_score=80, freshness_score=90, auth_status='green',
                quality_score=85, **kw,
            )['score']
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_poor_fit_red_scores_low(self):
        low = golden_opportunity_score(
            match_score=35, freshness_score=20, auth_status='red',
            quality_score=30,
        )['score']
        high = golden_opportunity_score(
            match_score=95, freshness_score=95, auth_status='green',
            quality_score=95,
        )['score']
        self.assertLess(low, high)

    def test_contact_does_not_dominate(self):
        """A slightly worse job with a great contact must NOT leapfrog a far
        better job with no contact (contact weight is modest by design)."""
        no_contact_strong = golden_opportunity_score(
            match_score=95, freshness_score=90, auth_status='green',
            quality_score=90,
        )['score']
        # A dramatically worse fit but with a great contact should not win.
        with_contact_weak = golden_opportunity_score(
            match_score=55, freshness_score=50, auth_status='unknown',
            quality_score=50, contact_relevance_score=99,
        )['score']
        self.assertGreater(no_contact_strong, with_contact_weak)

    def test_breakdown_explainable(self):
        r = golden_opportunity_score(
            match_score=80, freshness_score=90, auth_status='green',
            quality_score=80, effort_estimate='10-20 min',
        )
        self.assertIn('breakdown', r)
        self.assertIn('weights', r)
        self.assertAlmostEqual(sum(r['weights'].values()), 1.0, places=1)


if __name__ == '__main__':
    unittest.main()