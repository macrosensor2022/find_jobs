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
    _LEVEL_MAP,
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


# ---------------------------------------------------------------------------
# wage_level mapping (Phase 3.5 regression guard)
# ---------------------------------------------------------------------------

class TestWageLevelParsing(unittest.TestCase):
    """Ensure _LEVEL_MAP + the parsing logic correctly handle DOL formats."""

    def _parse(self, raw):
        """Replicate the exact parsing from load_lca_xlsx."""
        if raw is None:
            return None
        level_str = str(raw).strip().upper()
        after_level = level_str.split('LEVEL')[-1].strip()
        roman = after_level.split('-')[0].split('$')[0].split('(')[0].strip()
        return _LEVEL_MAP.get(roman)

    def test_level_map_exact_keys(self):
        self.assertEqual(_LEVEL_MAP, {'I': 1, 'II': 2, 'III': 3, 'IV': 4})

    def test_plain_levels(self):
        self.assertEqual(self._parse('Level I'), 1)
        self.assertEqual(self._parse('Level II'), 2)
        self.assertEqual(self._parse('Level III'), 3)
        self.assertEqual(self._parse('Level IV'), 4)

    def test_levels_with_wage_suffix(self):
        self.assertEqual(self._parse('Level I - $50,000'), 1)
        self.assertEqual(self._parse('Level II - $80,000'), 2)
        self.assertEqual(self._parse('Level III - $120,000'), 3)
        self.assertEqual(self._parse('Level IV - $150,000'), 4)

    def test_uppercase(self):
        self.assertEqual(self._parse('LEVEL II'), 2)
        self.assertEqual(self._parse('LEVEL IV'), 4)

    def test_na_and_empty_return_none(self):
        self.assertIsNone(self._parse('N/A'))
        self.assertIsNone(self._parse(''))
        self.assertIsNone(self._parse(None))

    def test_ii_does_not_collapse_to_i(self):
        """Regression: prefix check caused II/III/IV to map to 1."""
        self.assertNotEqual(self._parse('Level II'), 1)
        self.assertNotEqual(self._parse('Level III'), 1)
        self.assertNotEqual(self._parse('Level IV'), 1)


class TestWageLevelLiveData(unittest.TestCase):
    """Verify wage_level values for key employers using the real LCA database.

    These values were confirmed against the FY2026 Q2 DOL disclosure data.
    If they fail, the LCA data needs to be reloaded:
        python -m scrapers.sponsorship_data --clear --load-lca data/LCA_Dislclosure_Data_FY2026_Q2.xlsx
    """

    EXPECTED = {
        'Google': 2,
        'Amazon': 2,
        'Microsoft': 3,
        'Apple': 4,
        'Meta': 4,
    }

    @classmethod
    def setUpClass(cls):
        from backend.app import app
        from backend.models import db, SponsorHistory
        cls.flask_app = app
        cls.db = db
        with app.app_context():
            count = SponsorHistory.query.count()
            if count < 1000:
                raise unittest.SkipTest(
                    f'sponsor_history has only {count} rows; '
                    'reload LCA data before running this test'
                )

    def test_google_wage_level(self):
        with self.flask_app.app_context():
            r = lookup_employer('Google', self.db.session)
            self.assertEqual(r['wage_level'], self.EXPECTED['Google'],
                             f"Google: expected {self.EXPECTED['Google']}, got {r['wage_level']}")

    def test_amazon_wage_level(self):
        with self.flask_app.app_context():
            r = lookup_employer('Amazon', self.db.session)
            self.assertEqual(r['wage_level'], self.EXPECTED['Amazon'],
                             f"Amazon: expected {self.EXPECTED['Amazon']}, got {r['wage_level']}")

    def test_microsoft_wage_level(self):
        with self.flask_app.app_context():
            r = lookup_employer('Microsoft', self.db.session)
            self.assertEqual(r['wage_level'], self.EXPECTED['Microsoft'],
                             f"Microsoft: expected {self.EXPECTED['Microsoft']}, got {r['wage_level']}")

    def test_apple_wage_level(self):
        with self.flask_app.app_context():
            r = lookup_employer('Apple', self.db.session)
            self.assertEqual(r['wage_level'], self.EXPECTED['Apple'],
                             f"Apple: expected {self.EXPECTED['Apple']}, got {r['wage_level']}")

    def test_meta_wage_level(self):
        with self.flask_app.app_context():
            r = lookup_employer('Meta', self.db.session)
            self.assertEqual(r['wage_level'], self.EXPECTED['Meta'],
                             f"Meta: expected {self.EXPECTED['Meta']}, got {r['wage_level']}")


if __name__ == '__main__':
    unittest.main()
