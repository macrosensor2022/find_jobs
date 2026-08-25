"""Experience-level filtering tests (EXP_YEARS gate)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.profile_matcher import ProfileMatcher


class TestExperienceHardDrop(unittest.TestCase):
    def setUp(self):
        self.pm = ProfileMatcher()
        self.min_score = 25

    def test_senior_5plus_years_dropped(self):
        """Senior Data Engineer, 5+ years must score below min and be dropped."""
        job = {
            'title': 'Senior Data Engineer, 5+ years',
            'description': (
                'We need a Senior Data Engineer with 5+ years of experience '
                'building ETL pipelines in Python and SQL Server / SSIS.'
            ),
            'location': 'Boston, MA',
            'company': 'Acme Corp',
        }
        score, skills = self.pm.calculate_match_score(job)
        self.assertEqual(score, 0)
        self.assertTrue(job.get('exp_hard_drop'))
        self.assertLess(score, self.min_score)

        kept = self.pm.filter_jobs_by_match([job], min_score=self.min_score)
        self.assertEqual(kept, [])

    def test_new_grad_passes(self):
        """Data Engineer, New Grad must pass the experience gate and keep score."""
        job = {
            'title': 'Data Engineer, New Grad',
            'description': (
                'University graduate / early career Data Engineer role. '
                'Python, SQL, ETL. Entry level — 0-1 years preferred.'
            ),
            'location': 'Hartford, CT',
            'company': 'Bangor Savings Bank',
        }
        score, skills = self.pm.calculate_match_score(job)
        self.assertFalse(job.get('exp_hard_drop'))
        self.assertGreaterEqual(score, self.min_score)
        self.assertTrue(job.get('exp_boost') or 'exp_early_boost' in skills)

        kept = self.pm.filter_jobs_by_match([job], min_score=self.min_score)
        self.assertEqual(len(kept), 1)
        self.assertGreaterEqual(kept[0]['match_score'], self.min_score)


class TestExperienceSoftPenalty(unittest.TestCase):
    def setUp(self):
        self.pm = ProfileMatcher()

    def test_1_2_years_soft_penalty_not_dropped(self):
        job = {
            'title': 'Data Engineer',
            'description': 'Looking for 1-2 years of experience with SQL and Python ETL.',
            'location': 'Austin, TX',
            'company': 'MidSize Co',
        }
        score, _ = self.pm.calculate_match_score(job)
        self.assertFalse(job.get('exp_hard_drop'))
        self.assertTrue(job.get('exp_soft_penalty'))
        self.assertGreater(score, 0)

        kept = self.pm.filter_jobs_by_match([job], min_score=10)
        self.assertEqual(len(kept), 1)

    def test_2_years_preferred_soft(self):
        job = {
            'title': 'Junior Data Engineer',
            'description': '2 years preferred. Python, Azure, SSIS a plus.',
            'location': 'Columbus, OH',
            'company': 'InsureCo',
        }
        exp = self.pm.evaluate_experience(job)
        self.assertFalse(exp['hard_drop'])
        self.assertTrue(exp['soft_penalty'] or exp['boost'])


class TestYearsParsing(unittest.TestCase):
    def setUp(self):
        self.pm = ProfileMatcher()

    def test_minimum_3_years_hard_drop(self):
        exp = self.pm.parse_required_years(
            'Data Engineer',
            'Minimum 3 years of experience required with Spark.',
        )
        self.assertEqual(exp['required_years'], 3.0)
        self.assertTrue(exp['hard_drop'])

    def test_entry_level_zero(self):
        exp = self.pm.parse_required_years('Entry Level Data Analyst', '')
        self.assertEqual(exp['required_years'], 0.0)
        self.assertFalse(exp['hard_drop'])
        self.assertTrue(exp['boost'])

    def test_staff_title_hard_drop(self):
        exp = self.pm.parse_required_years('Staff Data Engineer', 'Great team.')
        self.assertTrue(exp['is_senior_title'])
        self.assertTrue(exp['hard_drop'])

    def test_intern_title_hard_drop_in_ft_mode(self):
        exp = self.pm.parse_required_years('Data Engineer Intern', 'Summer program.')
        self.assertTrue(exp['hard_drop'])

    def test_coop_title_hard_drop_in_ft_mode(self):
        exp = self.pm.parse_required_years('Data Engineer Co-op', 'Northeastern co-op.')
        self.assertTrue(exp['hard_drop'])

    def test_internal_not_treated_as_intern(self):
        exp = self.pm.parse_required_years(
            'Internal Audit Associate - Data Analytics Focus', ''
        )
        self.assertFalse(exp['hard_drop'])


if __name__ == '__main__':
    unittest.main()
