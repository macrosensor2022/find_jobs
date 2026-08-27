"""Tests for the explainable scoring engine (services/).

All fixtures here are clearly synthetic: companies are named TEST_*, so live
job data can never be confused with test data.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import freshness, quality, ranking
from services.experience import analyze_experience
from services.location_pref import detect_remote_type, score_location
from services.matching import evaluate_job, default_weights
from services.requirements import score_education, score_responsibilities
from services.role_classifier import classify_role, detect_seniority
from services.skills import extract_job_skills, score_skills
from services.sponsorship import assess_sponsorship


class TestRoleClassifier(unittest.TestCase):
    def test_tier1_exact(self):
        result = classify_role('Analytics Engineer')
        self.assertEqual(result['tier'], 1)
        self.assertGreaterEqual(result['score'], 90)

    def test_tier2_data_engineer(self):
        self.assertEqual(classify_role('Data Engineer')['tier'], 2)

    def test_tier3_data_scientist_ranked_below_tier1(self):
        tier1 = classify_role('Data Analyst')['score']
        tier3 = classify_role('Data Scientist')['score']
        self.assertGreater(tier1, tier3)

    def test_avoid_frontend(self):
        result = classify_role('Frontend Developer')
        self.assertTrue(result['avoid'])
        self.assertLess(result['score'], 20)
        self.assertTrue(result['reasons'])

    def test_pure_swe_titles_not_tiered(self):
        for title in ('Growth Engineer', 'Backend Engineer', 'Software Engineer'):
            result = classify_role(title)
            self.assertIsNone(result['tier'], msg=title)
            self.assertTrue(result['avoid'] or result['tier'] is None, msg=title)
    def test_senior_title_penalized_not_reclassified(self):
        result = classify_role('Senior Data Engineer')
        self.assertEqual(result['tier'], 2)
        self.assertEqual(result['seniority'], 'senior')
        self.assertLess(result['score'], classify_role('Data Engineer')['score'])

    def test_inexact_title_still_classified(self):
        result = classify_role('Data Platform Engineer II')
        self.assertIsNotNone(result['tier'])
        self.assertIn(result['method'], ('exact_phrase', 'token_overlap'))

    def test_unknown_title_not_hard_rejected(self):
        result = classify_role('Insights Specialist')
        self.assertGreater(result['score'], 0)
        self.assertTrue(result['reasons'])

    def test_seniority_detection(self):
        self.assertEqual(detect_seniority('Staff Engineer'), 'senior')
        self.assertEqual(detect_seniority('New Grad Data Engineer'), 'entry')
        self.assertEqual(detect_seniority('Data Engineer Intern'), 'intern')
        self.assertEqual(detect_seniority('Data Engineer II'), 'mid')


class TestExperience(unittest.TestCase):
    def test_five_years_hard_drop(self):
        result = analyze_experience(
            'Data Engineer',
            'We require 5+ years of experience building data pipelines.',
        )
        self.assertTrue(result['hard_drop'])
        self.assertEqual(result['score'], 0.0)
        self.assertTrue(result['evidence'])

    def test_senior_title_hard_drop(self):
        self.assertTrue(analyze_experience('Senior Data Engineer', 'Build pipelines.')['hard_drop'])

    def test_new_grad_scores_high(self):
        result = analyze_experience(
            'Data Engineer, New Grad',
            'This is an entry-level role for recent graduates. 0-2 years experience.',
        )
        self.assertFalse(result['hard_drop'])
        self.assertGreaterEqual(result['score'], 90)
        self.assertTrue(result['is_early_career'])

    def test_company_age_is_not_an_experience_requirement(self):
        result = analyze_experience(
            'Data Analyst',
            'TEST_ACME was founded over 30 years ago and has served clients for 20 years.',
        )
        self.assertFalse(result['hard_drop'])
        self.assertIsNone(result['required_years'])

    def test_preferred_years_does_not_hard_drop(self):
        result = analyze_experience(
            'Data Engineer',
            '1 year of experience required. 4 years of Spark preferred.',
        )
        self.assertFalse(result['hard_drop'])
        self.assertEqual(result['required_years'], 1.0)
        self.assertTrue(result['risks'])

    def test_two_years_survives_with_penalty(self):
        result = analyze_experience('Data Analyst', 'Minimum of 2 years of experience.')
        self.assertFalse(result['hard_drop'])
        self.assertLess(result['score'], 95)

    def test_internship_dropped_in_fulltime_mode(self):
        self.assertTrue(analyze_experience('Data Engineer Intern', 'Summer internship.')['hard_drop'])


class TestSponsorship(unittest.TestCase):
    def test_red_no_sponsorship_with_evidence(self):
        result = assess_sponsorship(
            'Data Engineer',
            'Candidates must not require sponsorship now or in the future.',
        )
        self.assertEqual(result['status'], 'red')
        self.assertIn('sponsorship', result['evidence'].lower())
        self.assertEqual(result['evidence_source'], 'job_description')
        self.assertEqual(result['score'], 0.0)

    def test_red_citizenship(self):
        result = assess_sponsorship('Data Engineer', 'Applicants must be a US citizen.')
        self.assertEqual(result['status'], 'red')

    def test_red_clearance(self):
        result = assess_sponsorship('Data Engineer', 'An active security clearance is required.')
        self.assertEqual(result['status'], 'red')

    def test_green_explicit_sponsorship(self):
        result = assess_sponsorship('Data Engineer', 'Visa sponsorship is available for this role.')
        self.assertEqual(result['status'], 'green')
        self.assertTrue(result['evidence'])

    def test_yellow_when_mentioned_without_position(self):
        result = assess_sponsorship(
            'Data Engineer',
            'You must be legally authorized to work in the United States.',
        )
        self.assertEqual(result['status'], 'yellow')
        self.assertTrue(result['evidence'])

    def test_unknown_when_silent(self):
        result = assess_sponsorship('Data Engineer', 'Build pipelines with Python and SQL.')
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['evidence'])

    def test_never_infers_from_employer(self):
        # A well-known sponsor name must not produce green on its own.
        result = assess_sponsorship('Data Engineer at Google', 'Work on data systems.')
        self.assertEqual(result['status'], 'unknown')

    def test_feed_hint_trusted_with_provenance(self):
        result = assess_sponsorship('Data Engineer', '', feed_hint='no_sponsorship',
                                    source='github_newgrad')
        self.assertEqual(result['status'], 'red')
        self.assertEqual(result['evidence_source'], 'github_newgrad')

    def test_real_world_phrasings(self):
        """Phrasings taken from postings actually present in the database."""
        red = [
            'GM does not provide immigration-related sponsorship for this role.',
            'This position is not eligible for visa sponsorship.',
            'Sponsorship is not available for this position.',
            'We are unable to sponsor or take over sponsorship of an employment visa.',
            'No visa sponsorship is provided.',
            'We do not sponsor H-1B visas.',
            'Must be authorized to work in the US. No sponsorship required.',
            'Employment is contingent on being able to work without sponsorship.',
            'We will not provide immigration sponsorship for this opening.',
            'The company is not offering visa sponsorship at this time.',
        ]
        for text in red:
            with self.subTest(text=text):
                result = assess_sponsorship('Data Engineer', text)
                self.assertEqual(result['status'], 'red', result['reason'])
                self.assertTrue(result['evidence'], 'RED must carry evidence')

        green = [
            'We offer visa sponsorship for eligible candidates.',
            'We are an E-Verify employer.',
            'We will sponsor H-1B for exceptional candidates.',
        ]
        for text in green:
            with self.subTest(text=text):
                self.assertEqual(assess_sponsorship('DE', text)['status'], 'green')

    def test_evidence_is_verbatim_from_text(self):
        text = ('We build data platforms. '
                'Sponsorship is not available for this position. '
                'Apply today.')
        result = assess_sponsorship('Data Engineer', text)
        self.assertIn(result['evidence'].rstrip('.'), text)


class TestSkills(unittest.TestCase):
    def test_no_substring_false_positive(self):
        # 'ssis' must not match 'assistant'
        self.assertNotIn('SSIS', extract_job_skills('trading assistant role'))

    def test_matched_and_missing_reported(self):
        result = score_skills(
            'build etl pipelines with python, sql and dbt on snowflake',
            [('Python', 'language', 5), ('SQL', 'language', 5), ('ETL', 'etl', 5)],
        )
        self.assertIn('Python', result['matched'])
        self.assertIn('dbt', result['missing'])
        self.assertIn('Snowflake', result['missing'])

    def test_no_skills_found_is_honest(self):
        result = score_skills('great culture and free snacks', [('Python', 'language', 5)])
        self.assertEqual(result['confidence'], 'low')
        self.assertIsNotNone(result['note'])

    def test_full_match_scores_higher_than_partial(self):
        profile = [('Python', 'language', 5), ('SQL', 'language', 5)]
        full = score_skills('python and sql required', profile)['score']
        partial = score_skills('python, sql, kubernetes, terraform, scala, kafka', profile)['score']
        self.assertGreater(full, partial)


class TestResponsibilitiesAndEducation(unittest.TestCase):
    def test_responsibilities_detected(self):
        result = score_responsibilities(
            'you will build data pipelines, write sql, and create dashboards in power bi'
        )
        self.assertIn('pipeline_build', result['present'])
        self.assertIn('reporting_bi', result['present'])
        self.assertGreater(result['score'], 70)

    def test_thin_description_low_confidence(self):
        result = score_responsibilities('join our team')
        self.assertEqual(result['confidence'], 'low')

    def test_masters_satisfies_bachelors(self):
        result = score_education("Bachelor's degree in Computer Science required.")
        self.assertEqual(result['score'], 100.0)
        self.assertEqual(result['required'], 'bachelors')
        self.assertTrue(result['evidence'])

    def test_phd_requirement_penalized(self):
        result = score_education('PhD required in machine learning.')
        self.assertLess(result['score'], 50)
        self.assertTrue(result['risks'])

    def test_no_degree_mentioned(self):
        result = score_education('Build pipelines.')
        self.assertIsNone(result['required'])


class TestLocation(unittest.TestCase):
    def test_preferred_state(self):
        result = score_location('Boston, MA', state='MA')
        self.assertEqual(result['score'], 100.0)

    def test_excluded_state(self):
        result = score_location('San Francisco, CA', state='CA')
        self.assertLess(result['score'], 30)
        self.assertTrue(result['risks'])

    def test_remote_us(self):
        result = score_location('Remote - US', state='REMOTE')
        self.assertGreater(result['score'], 85)

    def test_non_us_rejected(self):
        result = score_location('Bengaluru, India')
        self.assertLess(result['score'], 20)

    def test_remote_type_detection(self):
        self.assertEqual(detect_remote_type('Boston, MA (Hybrid)'), 'hybrid')
        self.assertEqual(detect_remote_type('Remote'), 'remote')
        self.assertEqual(detect_remote_type('Boston, MA', 'This is an on-site role'), 'onsite')

    def test_unknown_location_is_not_guessed(self):
        result = score_location('', '')
        self.assertEqual(result['score'], 50.0)
        self.assertTrue(result['risks'])


class TestFreshness(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

    def test_buckets(self):
        cases = [(2, 'hot'), (48, 'fresh'), (120, 'recent'), (300, 'aging'), (500, 'stale')]
        for hours, expected in cases:
            posted = self.now - timedelta(hours=hours)
            self.assertEqual(freshness.evaluate(posted, now=self.now)['bucket'], expected)

    def test_unknown_date_not_fabricated(self):
        result = freshness.evaluate(None, now=self.now)
        self.assertEqual(result['bucket'], 'unknown')
        self.assertIsNone(result['hours'])
        self.assertFalse(result['is_known'])

    def test_unknown_date_never_expires(self):
        self.assertFalse(freshness.is_expired(None, now=self.now))

    def test_old_job_expires(self):
        old = self.now - timedelta(days=60)
        self.assertTrue(freshness.is_expired(old, expiry_days=30, now=self.now))


class TestQuality(unittest.TestCase):
    def _job(self, **overrides):
        job = {
            'company': 'TEST_ACME Analytics',
            'source': 'greenhouse',
            'description': 'x' * 500,
            'date_posted': datetime.now(timezone.utc),
            'application_url': 'https://boards.greenhouse.io/test/jobs/1',
            'application_url_status': 'verified',
            'verification_status': 'active',
            'is_expired': False,
        }
        job.update(overrides)
        return job

    def test_clean_job_scores_high(self):
        self.assertGreaterEqual(quality.evaluate_quality(self._job())['score'], 95)

    def test_missing_apply_url_penalized(self):
        result = quality.evaluate_quality(self._job(application_url=None))
        self.assertLess(result['score'], 80)
        self.assertIn('No application URL captured', result['flags'])

    def test_placeholder_company_penalized(self):
        result = quality.evaluate_quality(self._job(company='See posting'))
        self.assertIn('Employer could not be identified', result['flags'])

    def test_unknown_date_penalized(self):
        result = quality.evaluate_quality(self._job(date_posted=None))
        self.assertIn('Posting date unknown', result['flags'])

    def test_search_fallback_url_penalized(self):
        result = quality.evaluate_quality(self._job(application_url_status='search_fallback'))
        self.assertIn('Only a search link is available, not a real apply page',
                      result['flags'])

    def test_duplicate_penalized(self):
        self.assertLess(
            quality.evaluate_quality(self._job(duplicate_of_id=5))['score'],
            quality.evaluate_quality(self._job())['score'],
        )


class TestRanking(unittest.TestCase):
    def test_weights_normalize_to_one(self):
        self.assertAlmostEqual(sum(default_weights().values()), 1.0, places=6)

    def test_quality_gate_beats_keyword_score(self):
        high_match_low_quality = ranking.final_score(95, 80, 20)
        lower_match_high_quality = ranking.final_score(82, 80, 100)
        self.assertGreater(lower_match_high_quality, high_match_low_quality)

    def test_final_score_blend(self):
        # match 100, opportunity 0, perfect quality -> 70
        self.assertAlmostEqual(ranking.final_score(100, 0, 100), 70.0, places=1)
        self.assertAlmostEqual(ranking.final_score(0, 100, 100), 30.0, places=1)


class TestEndToEndMatching(unittest.TestCase):
    def _strong_job(self):
        return {
            'title': 'Analytics Engineer, New Grad',
            'company': 'TEST_NORTHWIND Insurance',
            'location': 'Boston, MA',
            'worksite_state': 'MA',
            'source': 'greenhouse',
            'date_posted': datetime.now(timezone.utc),
            'application_url': 'https://boards.greenhouse.io/testnorthwind/jobs/9',
            'application_url_status': 'verified',
            'description': (
                "We are hiring a new grad Analytics Engineer. You will build ETL "
                "pipelines in Azure Data Factory, write complex SQL in SQL Server, "
                "model a data warehouse, run data quality validation, and build "
                "Power BI dashboards. Requires a Bachelor's degree and 0-2 years of "
                "experience. Python and Git experience preferred. Visa sponsorship "
                "is available for this position."
            ),
        }

    def _weak_job(self):
        return {
            'title': 'Senior Frontend Developer',
            'company': 'TEST_PIXELWORKS',
            'location': 'San Francisco, CA',
            'worksite_state': 'CA',
            'source': 'jsearch',
            'date_posted': datetime.now(timezone.utc) - timedelta(days=40),
            'application_url': None,
            'description': (
                'We need a Senior React developer with 8+ years of experience. '
                'Must be a US citizen. Build UI components in TypeScript.'
            ),
        }

    def test_strong_job_scores_high_and_explains(self):
        result = evaluate_job(self._strong_job())
        self.assertGreaterEqual(result['score'], 75)
        self.assertTrue(result['eligible'])
        self.assertIn('Python', result['reasons'])
        self.assertEqual(result['authorization']['status'], 'green')
        self.assertEqual(set(result['breakdown']), {
            'skills', 'responsibilities', 'experience', 'education',
            'role', 'location', 'authorization',
        })

    def test_weak_job_is_ineligible_with_named_disqualifiers(self):
        result = evaluate_job(self._weak_job())
        self.assertFalse(result['eligible'])
        self.assertTrue(result['disqualifiers'])
        self.assertLess(result['score'], result_score_of_strong_job())

    def test_score_job_pipeline_ranks_strong_above_weak(self):
        strong = ranking.score_job(self._strong_job())
        weak = ranking.score_job(self._weak_job())
        self.assertGreater(strong['final_score'], weak['final_score'])
        self.assertTrue(strong['eligible'])
        self.assertFalse(weak['eligible'])

    def test_gaps_only_list_skills_the_job_asked_for(self):
        job = self._strong_job()
        job['description'] += ' Experience with dbt and Kafka is a plus.'
        result = evaluate_job(job)
        self.assertIn('dbt', result['gaps'])
        self.assertIn('Kafka', result['gaps'])
        self.assertNotIn('Terraform', result['gaps'])

    def test_company_name_does_not_inflate_skills(self):
        job = self._strong_job()
        job['company'] = 'TEST_Spark Databricks Snowflake Kafka Inc'
        with_company = evaluate_job(job)['breakdown']['skills']
        job['company'] = 'TEST_NORTHWIND Insurance'
        without_company = evaluate_job(job)['breakdown']['skills']
        self.assertEqual(with_company, without_company)


    def test_location_prefs_are_not_hard_coded(self):
        result = score_location(
            'San Francisco, CA',
            state='CA',
            preferences={
                'preferred_states': ['CA'],
                'acceptable_states': [],
                'excluded_states': [],
                'allow_remote_us': True,
                'allow_hybrid': True,
                'allow_relocation': True,
            },
        )
        self.assertEqual(result['score'], 100.0)


class TestVerificationAndQuality(unittest.TestCase):
    def test_missing_url_is_unknown_not_guessed(self):
        from services.verification import verify_url

        result = verify_url('')
        self.assertEqual(result['url_status'], 'unknown')
        self.assertEqual(result['verification_status'], 'unverified')
        self.assertIn('No application URL', result['detail'])

    def test_unverified_url_lowers_quality_but_does_not_invent_a_link(self):
        from services.quality import evaluate_quality

        result = evaluate_quality({
            'company': 'TEST_NORTHWIND',
            'description': 'x' * 400,
            'source': 'greenhouse',
            'application_url': 'https://example.com/jobs/test-apply',
            'application_url_status': 'unverified',
        })
        self.assertTrue(any('not yet verified' in f.lower() for f in result['flags']))

    def test_missing_apply_url_is_flagged(self):
        from services.quality import evaluate_quality

        result = evaluate_quality({
            'company': 'TEST_NORTHWIND',
            'description': 'x' * 400,
            'source': 'greenhouse',
        })
        self.assertTrue(any('no application url' in f.lower() for f in result['flags']))


class TestDedupeAndCanApplyContract(unittest.TestCase):
    def test_same_company_title_location_share_a_key(self):
        from services.dedupe import build_dedupe_key

        a = build_dedupe_key({
            'company': 'TEST_NORTHWIND',
            'title': 'Analytics Engineer',
            'location': 'Boston, MA',
            'application_url': 'https://boards.greenhouse.io/test/jobs/1',
        })
        b = build_dedupe_key({
            'company': 'Test Northwind',
            'title': 'Analytics Engineer',
            'location': 'Boston, MA',
            'job_url': 'https://boards.greenhouse.io/test/jobs/1',
        })
        self.assertEqual(a, b)
        self.assertTrue(a)


def result_score_of_strong_job():
    return evaluate_job(TestEndToEndMatching()._strong_job())['score']


if __name__ == '__main__':
    unittest.main(verbosity=2)
