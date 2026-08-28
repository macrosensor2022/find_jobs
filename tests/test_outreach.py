"""Tests for V3 outreach preparation (services/outreach.py).

Reinforces the hard rule: outreach NEVER auto-sends and NEVER fabricates
authorization/demographic claims. All fixtures are synthetic TEST_* data.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.outreach import build_outreach, recommended_channel


def _job(**over):
    base = {
        'id': 1,
        'title': 'Test Data Engineer',
        'company': 'TEST_Bosch',
        'location': 'Remote',
        'description': 'We build ETL pipelines with SQL and Python.',
        'source': 'test',
    }
    base.update(over)
    return base


_CONTACT = {
    'contact_name': 'Jane Doe Smith',
    'contact_role': 'Engineering Manager',
    'contact_type': 'hiring_manager',
    'email': 'jane@test.example',
    'email_state': 'VERIFIED_PUBLIC',
}


def _profile(**over):
    base = {
        'name': 'Vinay Test',
        'email': 'test@example.com',
        'headline': 'Data Engineer',
    }
    base.update(over)
    return base


class TestRecommendedChannel(unittest.TestCase):
    def test_verified_email_suggests_email(self):
        self.assertEqual(recommended_channel(_CONTACT), 'EMAIL')

    def test_no_email_no_linkedin_is_unknown(self):
        contact = dict(_CONTACT, email=None, email_state='NOT_FOUND')
        self.assertEqual(recommended_channel(contact), 'UNKNOWN')

    def test_linkedin_suggests_linkedin(self):
        contact = dict(_CONTACT, email=None, email_state='NOT_FOUND',
                       linkedin_url='https://linkedin.com/in/jane')
        self.assertEqual(recommended_channel(contact), 'LINKEDIN')


class TestBuildOutreachNoAutoSend(unittest.TestCase):
    def test_no_auto_send_flag_always_true(self):
        o = build_outreach(_job(), contact=_CONTACT, profile=_profile())
        self.assertTrue(o['no_auto_send'])

    def test_no_contact_gives_unknown_channel(self):
        o = build_outreach(_job(), contact={}, profile=_profile())
        self.assertEqual(o['channel'], 'UNKNOWN')
        self.assertTrue(o['no_auto_send'])

    def test_does_not_invent_authorization(self):
        o = build_outreach(_job(), contact={}, profile=_profile())
        for key in ('authorization_status', 'work_authorization'):
            if key in o:
                self.assertIsNone(o[key])


class TestOutreachContent(unittest.TestCase):
    def test_contact_name_included_when_verified(self):
        o = build_outreach(_job(), contact=_CONTACT, profile=_profile())
        self.assertIn('Jane Doe', o['email'])

    def test_email_draft_uses_role_and_skills(self):
        o = build_outreach(
            _job(),
            contact=_CONTACT, profile=_profile(),
            matched_skills=['SQL', 'Python'],
        )
        body = o['email']
        self.assertIn('Data Engineer', body)
        self.assertIn('SQL', body)


if __name__ == '__main__':
    unittest.main()