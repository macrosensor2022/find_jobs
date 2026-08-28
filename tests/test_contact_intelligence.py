"""Tests for V3 contact intelligence (services/contact_intelligence.py).

All fixtures use clearly synthetic TEST_* companies and fake names.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.contact_intelligence import (
    discover, should_search_contacts, contact_relevance,
)


def _job(**over):
    base = {
        'company': 'TEST_Bosch',
        'candidate_match_score': 88.0,
        'application_priority_score': 90.0,
        'application_url_status': 'verified',
        'role_family': 'DATA_ENGINEERING',
        'contact_hints': [],
    }
    base.update(over)
    return base


class TestContactGating(unittest.TestCase):
    def test_low_priority_not_searched(self):
        job = _job(application_priority_score=30)
        self.assertFalse(should_search_contacts(job))

    def test_high_priority_verified_searched(self):
        job = _job()
        self.assertTrue(should_search_contacts(job))

    def test_unverified_url_blocks(self):
        job = _job(application_url_status='unverified')
        self.assertFalse(should_search_contacts(job))

    def test_weak_match_blocks(self):
        job = _job(candidate_match_score=40)
        self.assertFalse(should_search_contacts(job))


class TestDiscover(unittest.TestCase):
    def test_no_fabrication_when_nothing_known(self):
        result = discover(_job())
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['contacts'], [])

    def test_verified_email_saved_from_authoritative_source(self):
        job = _job(contact_hints=[{
            'name': 'Jane Doe Smith',
            'role': 'Engineering Manager',
            'source': 'company_team_page',
            'source_url': 'https://jobs-test.example/team',
            'email': 'jane.smith@testbos.example',
        }])
        result = discover(job)
        self.assertEqual(result['status'], 'found')
        c = result['contacts'][0]
        self.assertEqual(c['email_state'], 'VERIFIED_PUBLIC')
        self.assertTrue(c['email_verified'])
        self.assertEqual(c['contact_type'], 'hiring_manager')
        self.assertTrue(c['is_recommended'])

    def test_pattern_inferred_email_not_verified(self):
        job = _job(contact_hints=[{
            'name': 'John Q Public',
            'role': 'Recruiter',
            'source': 'search_result',
            'email': 'john.q@test.example.com',
        }])
        c = discover(job)['contacts'][0]
        self.assertEqual(c['email_state'], 'PATTERN_INFERRED')
        self.assertFalse(c['email_verified'])


class TestContactRelevance(unittest.TestCase):
    def test_hiring_manager_outranks_talent_acquisition(self):
        hm = contact_relevance('hiring_manager', company_name='TEST_Bos',
                               role_family='DATA_ENGINEERING')
        ta = contact_relevance('talent_acquisition', company_name='TEST_Bos',
                               role_family='DATA_ENGINEERING')
        self.assertGreater(hm, ta)

    def test_bounded_0_100(self):
        s = contact_relevance('hiring_manager', company_name='TEST_Bos')
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)


if __name__ == '__main__':
    unittest.main()