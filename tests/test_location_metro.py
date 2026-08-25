"""Tests for location canonicalizer, TARGET_STATES, and metro opportunity guardrail."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPortlandRule(unittest.TestCase):
    def test_bare_portland_is_maine(self):
        from scrapers.location_utils import canonicalize_location, load_cbsa_crosswalk
        try:
            load_cbsa_crosswalk()
        except FileNotFoundError:
            self.skipTest('Census crosswalk missing')
        loc = canonicalize_location('Portland')
        self.assertEqual(loc['state'], 'ME')
        self.assertTrue(loc['parse_ok'])

    def test_portland_oregon_explicit(self):
        from scrapers.location_utils import canonicalize_location, load_cbsa_crosswalk
        try:
            load_cbsa_crosswalk()
        except FileNotFoundError:
            self.skipTest('Census crosswalk missing')
        loc = canonicalize_location('Portland, OR')
        self.assertEqual(loc['state'], 'OR')

    def test_portland_maine_explicit(self):
        from scrapers.location_utils import canonicalize_location
        loc = canonicalize_location('Portland, Maine')
        self.assertEqual(loc['state'], 'ME')


class TestTargetStates(unittest.TestCase):
    def test_allowlist(self):
        from scrapers.location_utils import in_target_states
        self.assertTrue(in_target_states('TX', ['ME', 'TX', 'CT']))
        self.assertTrue(in_target_states('REMOTE', ['ME', 'TX']))
        self.assertFalse(in_target_states('CA', ['ME', 'TX']))
        self.assertFalse(in_target_states('WA', ['ME', 'TX']))

    def test_remote_us(self):
        from scrapers.location_utils import canonicalize_location
        loc = canonicalize_location('Flexible / Remote')
        self.assertTrue(loc['is_remote_us'])
        self.assertEqual(loc['state'], 'REMOTE')


class TestSocNormalize(unittest.TestCase):
    def test_formats(self):
        from scrapers.metro_opportunity import normalize_soc
        self.assertEqual(normalize_soc('15-1243.00'), '15-1243')
        self.assertEqual(normalize_soc('151243'), '15-1243')
        self.assertEqual(normalize_soc('15-2051'), '15-2051')


class TestLcaGuardrail(unittest.TestCase):
    def test_empty_raises(self):
        from scrapers.metro_opportunity import assert_lca_data_present
        from unittest.mock import MagicMock, patch

        session = MagicMock()

        class _Q:
            def filter(self, *a, **k):
                return self
            def count(self):
                return 0

        session.query.side_effect = lambda *a, **k: _Q()
        with self.assertRaises(AssertionError) as ctx:
            assert_lca_data_present(session, fiscal_years=[2099, 2098, 2097])
        self.assertIn('LCA guardrail', str(ctx.exception))


class TestRankBlend(unittest.TestCase):
    def test_rank_score(self):
        from scrapers.metro_opportunity import compute_rank_score
        score = compute_rank_score(80, 0.9, 60, 70)
        self.assertGreater(score, 50)
        self.assertLessEqual(score, 100)


if __name__ == '__main__':
    unittest.main()
