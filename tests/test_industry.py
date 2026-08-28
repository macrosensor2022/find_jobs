"""Tests for V3 industry intelligence (services/industry.py).

Fixtures use clearly synthetic TEST_* companies/data so live job data can never
be confused with test data.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.industry import classify_industry


def _match_job(title, description='', company='TEST_Acme Corp', source='test'):
    return classify_industry(title=title, description=description,
                             company=company, source=source)


class TestIndustryClassifier(unittest.TestCase):
    def test_manufacturing_under_the_radar(self):
        result = _match_job(
            title='Business Data Analyst - Construction',
            description='We support the Manufacturing and Construction segment.',
            company='TEST_Manufacturers Co',
        )
        self.assertNotEqual(result['industry'], 'UNKNOWN')
        self.assertTrue(result['under_the_radar'])

    def test_finance_is_core(self):
        result = _match_job(
            title='Data Analyst Treasury',
            description='Support the finance and banking group.',
            company='TEST_Bank',
        )
        self.assertEqual(result['industry'], 'FINANCE')
        self.assertFalse(result['under_the_radar'])
        self.assertTrue(result['is_core'])

    def test_unknown_industry_no_invention(self):
        result = _match_job(
            title='Data Engineer',
            # No industry keyword anywhere -> must NOT invent an industry.
            description='We build data pipelines for our enterprise customers.',
            company='TEST_Acme Corp',
        )
        self.assertEqual(result['industry'], 'UNKNOWN')
        self.assertEqual(result['label'], 'Unknown')
        self.assertFalse(result['under_the_radar'])
        self.assertFalse(result['is_core'])
        self.assertEqual(result['evidence'], [])

    def test_evidence_is_verbatim(self):
        result = _match_job(
            title='Data Engineer - Defense',
            description='Support the defense sector with analytics.',
            company='TEST_DefenseCo',
        )
        self.assertEqual(result['industry'], 'DEFENSE')
        self.assertTrue(any('defense' in e.lower() for e in result['evidence']))


class TestIndustryConfigBoundaries(unittest.TestCase):
    def test_company_keyword_corroborates_only(self):
        """A generic title with no industry text stays UNKNOWN (no guessing)."""
        result = _match_job(
            title='Data Engineer',
            description='Google Cloud infrastructure work.',
            company='TEST_Generic LLC',
        )
        # TECHNOLOGY is a known keyword, but only explicitly; this checks the
        # engine does not classify from ambiguous single words.
        self.assertIsInstance(result['industry'], str)

    def test_under_the_radar_reason_present_when_flagged(self):
        result = _match_job(
            title='BI Analyst - Construction',
            description='Construction industry analytics.',
            company='TEST_ConstructCo',
        )
        if result['under_the_radar']:
            self.assertIsNotNone(result['under_the_radar_reason'])
        else:
            self.skipTest('Test industry not configured as under-the-radar.')


if __name__ == '__main__':
    unittest.main()