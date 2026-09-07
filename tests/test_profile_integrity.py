"""The candidate profile has one owner, and scraping is not it.

``run_scrape.py`` used to rewrite name, email, GitHub, LinkedIn, target role
and graduation date on every run, so any edit made on the Profile page was
silently reverted the next time a scrape ran from the CLI. It also wrote a
target role of "Co-op, Internship, New Grad", contradicting the full-time
new-grad search the whole product is built around.

Separately, the graduation date existed in three places with two different
values (a literal in ``backend/app.py``, ``Config.EDUCATION``, and the stored
profile), and the sidebar hardcoded one person's name, school and GitHub
avatar URL into ``index.html``.
"""

import os
import pathlib
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestScrapeNeverWritesTheProfile(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'run_scrape.py').read_text(encoding='utf-8')

    def test_no_profile_field_assignments(self):
        # `profile.<field> = ...` is the exact shape of the removed block.
        writes = re.findall(r'^\s*profile\.\w+\s*=(?!=)', self.source, re.M)
        self.assertEqual(writes, [], f'run_scrape.py assigns to profile: {writes}')

    def test_no_commit_of_profile_changes(self):
        # It reads the profile only; a session commit there would be suspicious.
        self.assertNotIn('db.session.commit()', self.source)

    def test_no_hardcoded_identity(self):
        lowered = self.source.lower()
        for token in ('vinay', 'macrosensor', 'varsvinay', 'linkedin.com/in/'):
            self.assertNotIn(token, lowered, f'{token!r} is hardcoded in run_scrape.py')

    def test_does_not_import_date_for_a_grad_date(self):
        self.assertNotIn('profile.grad_date', self.source)


class TestGraduationDateHasOneSource(unittest.TestCase):
    def test_config_derives_it_from_education(self):
        self.assertEqual(Config.grad_date(), date(2027, 12, 15))

    def test_it_matches_the_current_education_entry(self):
        current = next(e for e in Config.EDUCATION if e.get('is_current'))
        self.assertEqual(current['end_date'], Config.grad_date().isoformat())

    def test_no_second_literal_in_the_backend(self):
        source = (ROOT / 'backend' / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('_GRAD_DATE', source,
                         'the app must derive the date from Config.EDUCATION')

    def test_it_agrees_with_the_profile_summary(self):
        # PROFILE_SUMMARY is synced from LinkedIn and says Dec 2027.
        self.assertIn('Dec 2027', Config.PROFILE_SUMMARY)
        self.assertEqual(Config.grad_date().year, 2027)
        self.assertEqual(Config.grad_date().month, 12)

    def test_returns_none_rather_than_guessing(self):
        class NoEducation(Config):
            EDUCATION = []

        class Undated(Config):
            EDUCATION = [{'degree': 'MS', 'is_current': True, 'end_date': None}]

        self.assertIsNone(NoEducation.grad_date())
        self.assertIsNone(Undated.grad_date())


class TestUiDoesNotHardcodeTheProfile(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / 'frontend' / 'templates' / 'index.html').read_text(
            encoding='utf-8')
        self.js = (ROOT / 'frontend' / 'static' / 'js' / 'app.js').read_text(
            encoding='utf-8')

    def test_no_personal_identity_in_the_template(self):
        lowered = self.html.lower()
        for token in ('vinay', 'macrosensor', 'varsvinay'):
            self.assertNotIn(token, lowered, f'{token!r} is hardcoded in index.html')

    def test_sidebar_placeholders_exist_for_the_api_to_fill(self):
        for element_id in ('sidebarProfileName', 'sidebarProfileRole',
                           'sidebarProfileAvatar'):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_sidebar_is_populated_from_the_profile_endpoint(self):
        self.assertIn('loadSidebarProfile', self.js)
        self.assertIn("fetchAPI('/profile')", self.js)
        self.assertIn('sidebarProfileName', self.js)

    def test_no_outbound_avatar_request(self):
        # The avatar used to be <img src="https://github.com/<user>.png">,
        # which fetched a third-party image on every page load.
        self.assertNotIn('github.com/macrosensor2022.png', self.html)
        self.assertNotRegex(self.html, r'<img[^>]+src="https://github\.com')

    def test_profile_inputs_are_not_pre_filled_with_an_identity(self):
        for field in ('profileName', 'profileGithub'):
            match = re.search(rf'id="{field}"[^>]*>', self.html)
            self.assertIsNotNone(match, field)
            self.assertNotIn('value="', match.group(0),
                             f'{field} carries a hardcoded value')


if __name__ == '__main__':
    unittest.main()
