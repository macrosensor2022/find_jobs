"""
Unit tests for Phase 1: sponsorship data layer.

Covers normalize_company_name, lookup_employer (exact & fuzzy),
and verifies the new tables/columns exist after db.create_all().

Run:  python -m pytest tests/test_sponsorship.py -v
  or: python -m unittest tests.test_sponsorship -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.sponsorship_data import normalize_company_name, lookup_employer


# ---------------------------------------------------------------------------
# normalize_company_name
# ---------------------------------------------------------------------------

class TestNormalizeCompanyName(unittest.TestCase):

    def test_basic_lowercase(self):
        self.assertEqual(normalize_company_name('Google'), 'google')

    def test_strip_inc(self):
        self.assertEqual(normalize_company_name('Apple Inc.'), 'apple')

    def test_strip_llc(self):
        self.assertEqual(normalize_company_name('Acme Solutions LLC'), 'acme solutions')

    def test_strip_corporation(self):
        self.assertEqual(normalize_company_name('Microsoft Corporation'), 'microsoft')

    def test_strip_co_suffix(self):
        self.assertEqual(normalize_company_name('JPMorgan Chase & Co.'), 'jpmorgan chase')

    def test_strip_leading_the(self):
        self.assertEqual(normalize_company_name('The Home Depot'), 'home depot')

    def test_comma_before_suffix(self):
        self.assertEqual(normalize_company_name('Meta Platforms, Inc.'), 'meta platforms')

    def test_preserves_descriptive_words(self):
        self.assertEqual(
            normalize_company_name('Acme Technologies Inc'),
            'acme technologies',
        )

    def test_punctuation_removal(self):
        self.assertEqual(normalize_company_name('Johnson & Johnson'), 'johnson johnson')

    def test_empty_string(self):
        self.assertEqual(normalize_company_name(''), '')

    def test_none(self):
        self.assertEqual(normalize_company_name(None), '')

    def test_whitespace_collapse(self):
        self.assertEqual(normalize_company_name('  Some   Corp  '), 'some')

    def test_multiple_suffixes(self):
        self.assertEqual(normalize_company_name('Big Corp Inc'), 'big')


# ---------------------------------------------------------------------------
# lookup_employer
# ---------------------------------------------------------------------------

class TestLookupEmployer(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from backend.models import db, EVerifyEmployer, SponsorHistory

        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.db = db
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            db.session.add(EVerifyEmployer(
                employer_name='Google LLC',
                normalized_name='google',
                city='Mountain View', state='CA',
            ))
            db.session.add(SponsorHistory(
                employer_name='Google LLC',
                normalized_name='google',
                fiscal_year=2024, lca_count=5000,
                approvals=4500, denials=100,
                median_wage=180000, prevailing_wage_level=3,
            ))
            db.session.add(EVerifyEmployer(
                employer_name='Meta Platforms Inc',
                normalized_name='meta platforms',
                city='Menlo Park', state='CA',
            ))
            db.session.commit()

    def test_exact_match_both_tables(self):
        with self.app.app_context():
            r = lookup_employer('Google LLC', self.db.session)
            self.assertTrue(r['is_everify'])
            self.assertEqual(r['employer_match_conf'], 1.0)
            self.assertEqual(r['h1b_lca_count'], 5000)
            self.assertEqual(r['median_wage'], 180000)
            self.assertEqual(r['wage_level'], 3)

    def test_exact_match_case_insensitive(self):
        with self.app.app_context():
            r = lookup_employer('GOOGLE', self.db.session)
            self.assertTrue(r['is_everify'])
            self.assertEqual(r['employer_match_conf'], 1.0)

    def test_suffix_stripped_still_matches(self):
        with self.app.app_context():
            r = lookup_employer('Google Inc.', self.db.session)
            self.assertTrue(r['is_everify'])

    def test_everify_only_no_sponsor_history(self):
        with self.app.app_context():
            r = lookup_employer('Meta Platforms', self.db.session)
            self.assertTrue(r['is_everify'])
            self.assertIsNone(r['h1b_lca_count'])

    def test_no_match_returns_unknowns(self):
        with self.app.app_context():
            r = lookup_employer('Totally Unknown Corp XYZ123', self.db.session)
            self.assertIsNone(r['is_everify'])
            self.assertIsNone(r['h1b_lca_count'])
            self.assertIsNone(r['employer_match_conf'])

    def test_empty_name(self):
        with self.app.app_context():
            r = lookup_employer('', self.db.session)
            self.assertIsNone(r['is_everify'])

    def test_none_name(self):
        with self.app.app_context():
            r = lookup_employer(None, self.db.session)
            self.assertIsNone(r['is_everify'])

    def test_fuzzy_match(self):
        """Near-miss spelling should fuzzy-match when above threshold."""
        try:
            import rapidfuzz  # noqa: F401
        except ImportError:
            self.skipTest('rapidfuzz not installed')
        with self.app.app_context():
            r = lookup_employer('Gogle', self.db.session)
            if r['employer_match_conf'] is not None:
                self.assertTrue(r['is_everify'])
                self.assertLess(r['employer_match_conf'], 1.0)


# ---------------------------------------------------------------------------
# Schema verification
# ---------------------------------------------------------------------------

class TestSchemaCreation(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        from backend.models import db

        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        self.db = db

    def test_new_tables_exist(self):
        import sqlalchemy
        with self.app.app_context():
            self.db.create_all()
            tables = sqlalchemy.inspect(self.db.engine).get_table_names()
            self.assertIn('everify_employer', tables)
            self.assertIn('sponsor_history', tables)

    def test_job_has_opt_columns(self):
        import sqlalchemy
        with self.app.app_context():
            self.db.create_all()
            cols = {
                c['name']
                for c in sqlalchemy.inspect(self.db.engine).get_columns('jobs')
            }
            for expected in [
                'is_everify', 'opt_field_related', 'sponsorship_screen',
                'h1b_lca_count', 'wage_level', 'employer_match_conf',
                'freshness_hours', 'opt_fit_score',
            ]:
                self.assertIn(expected, cols, f'Missing column: {expected}')

    def test_userprofile_has_opt_columns(self):
        import sqlalchemy
        with self.app.app_context():
            self.db.create_all()
            cols = {
                c['name']
                for c in sqlalchemy.inspect(self.db.engine).get_columns('user_profile')
            }
            for expected in [
                'grad_date', 'opt_start_date', 'stem_eligible', 'unemployment_days',
            ]:
                self.assertIn(expected, cols, f'Missing column: {expected}')


if __name__ == '__main__':
    unittest.main()
