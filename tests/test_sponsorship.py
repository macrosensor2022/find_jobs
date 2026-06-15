"""
Unit tests for OPT redesign (Phases 1 & 2).

Phase 1: normalize_company_name, lookup_employer, schema creation.
Phase 2: detect_sponsorship_screen, compute_opt_fit_score.

Run:  python -m pytest tests/test_sponsorship.py -v
  or: python -m unittest tests.test_sponsorship -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.sponsorship_data import (
    normalize_company_name, lookup_employer, batch_lookup_employers,
)


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

    def test_fuzzy_prefers_largest_employer_on_tie(self):
        """When multiple names tie in fuzzy score, pick highest lca_count."""
        try:
            import rapidfuzz  # noqa: F401
        except ImportError:
            self.skipTest('rapidfuzz not installed')
        from backend.models import SponsorHistory
        with self.app.app_context():
            self.db.session.add(SponsorHistory(
                employer_name='Acme Advertising LLC',
                normalized_name='acme advertising',
                fiscal_year=2026, lca_count=3,
                approvals=2, denials=0, median_wage=70000,
                prevailing_wage_level=1,
            ))
            self.db.session.add(SponsorHistory(
                employer_name='Acme.com Services LLC',
                normalized_name='acme com services',
                fiscal_year=2026, lca_count=5000,
                approvals=4000, denials=100, median_wage=150000,
                prevailing_wage_level=2,
            ))
            self.db.session.commit()

            r = lookup_employer('Acme', self.db.session)
            self.assertEqual(r['h1b_lca_count'], 5000)
            self.assertEqual(r['wage_level'], 2)


# ---------------------------------------------------------------------------
# batch_lookup_employers
# ---------------------------------------------------------------------------

class TestBatchLookupEmployers(unittest.TestCase):

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
                fiscal_year=2026, lca_count=3000,
                approvals=2800, denials=50,
                median_wage=190000, prevailing_wage_level=1,
            ))
            db.session.add(SponsorHistory(
                employer_name='Tiny Corp',
                normalized_name='tiny',
                fiscal_year=2026, lca_count=2,
                approvals=1, denials=0,
                median_wage=60000, prevailing_wage_level=3,
            ))
            db.session.commit()

    def test_returns_all_requested_names(self):
        with self.app.app_context():
            r = batch_lookup_employers(
                ['Google LLC', 'Unknown XYZ', ''],
                self.db.session,
            )
            self.assertIn('Google LLC', r)
            self.assertIn('Unknown XYZ', r)
            self.assertIn('', r)

    def test_exact_match(self):
        with self.app.app_context():
            r = batch_lookup_employers(['Google LLC'], self.db.session)
            g = r['Google LLC']
            self.assertTrue(g['is_everify'])
            self.assertEqual(g['h1b_lca_count'], 3000)
            self.assertEqual(g['wage_level'], 1)
            self.assertEqual(g['employer_match_conf'], 1.0)

    def test_unknown_returns_none_fields(self):
        with self.app.app_context():
            r = batch_lookup_employers(['NobodyCorp999'], self.db.session)
            g = r['NobodyCorp999']
            self.assertIsNone(g['is_everify'])
            self.assertIsNone(g['h1b_lca_count'])
            self.assertIsNone(g['wage_level'])

    def test_dedupes_normalized_names(self):
        """Google LLC and Google Inc should both resolve from one lookup."""
        with self.app.app_context():
            r = batch_lookup_employers(
                ['Google LLC', 'Google Inc.'],
                self.db.session,
            )
            self.assertEqual(r['Google LLC']['h1b_lca_count'], 3000)
            self.assertEqual(r['Google Inc.']['h1b_lca_count'], 3000)


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


# ---------------------------------------------------------------------------
# detect_sponsorship_screen (Phase 2)
# ---------------------------------------------------------------------------

class TestSponsorshipScreen(unittest.TestCase):

    def setUp(self):
        from scrapers.profile_matcher import ProfileMatcher
        self.matcher = ProfileMatcher()

    def test_detects_us_citizen_required(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'Data Engineer', 'Must be a US citizen to apply for this role.',
        ))

    def test_detects_will_not_sponsor(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'Data Analyst', 'We will not sponsor work visas for this position.',
        ))

    def test_detects_security_clearance(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'Systems Engineer', 'Security clearance required for this role.',
        ))

    def test_detects_no_sponsorship(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'ML Engineer', 'No sponsorship available.',
        ))

    def test_detects_without_sponsorship(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'BI Engineer', 'Must be authorized to work without sponsorship.',
        ))

    def test_clean_posting_returns_false(self):
        self.assertFalse(self.matcher.detect_sponsorship_screen(
            'Data Engineer', 'Looking for a skilled data engineer. Python and SQL required.',
        ))

    def test_html_description_cleaned(self):
        self.assertTrue(self.matcher.detect_sponsorship_screen(
            'Analyst', '<p>Must be a <b>U.S. citizen</b></p>',
        ))

    def test_none_inputs(self):
        self.assertFalse(self.matcher.detect_sponsorship_screen(None, None))


# ---------------------------------------------------------------------------
# compute_opt_fit_score (Phase 2)
# ---------------------------------------------------------------------------

class TestComputeOptFitScore(unittest.TestCase):

    @staticmethod
    def _compute(*a, **kw):
        from scrapers.profile_matcher import ProfileMatcher
        return ProfileMatcher.compute_opt_fit_score(*a, **kw)

    def test_base_score_passthrough(self):
        self.assertEqual(self._compute(60, None, False, False), 60)

    def test_everify_bonus(self):
        self.assertEqual(self._compute(60, True, False, False), 75)

    def test_field_related_bonus(self):
        self.assertEqual(self._compute(60, None, False, True), 65)

    def test_both_bonuses(self):
        self.assertEqual(self._compute(60, True, False, True), 80)

    def test_sponsorship_screen_caps_at_20(self):
        self.assertEqual(self._compute(80, True, True, True), 20)

    def test_capped_at_100(self):
        self.assertEqual(self._compute(95, True, False, True), 100)

    def test_zero_base(self):
        self.assertEqual(self._compute(0, None, False, False), 0)

    def test_none_base_treated_as_zero(self):
        self.assertEqual(self._compute(None, True, False, True), 20)

    def test_screen_with_low_base_stays_low(self):
        self.assertEqual(self._compute(10, False, True, False), 10)


if __name__ == '__main__':
    unittest.main()
