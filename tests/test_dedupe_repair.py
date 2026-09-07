"""The dedupe-key repair must never cost anyone a job.

``dedupe_key`` is written once at insert. When the normalization in
``services/dedupe.py`` changes, stored keys keep whatever the old algorithm
produced — ``rescore_job`` only fills NULLs (``key or build_dedupe_key(job)``),
so it never refreshes them.

The symptom was six genuinely different TikTok ML Engineer roles sharing one
key, because an older normalization discarded bracketed text. The repair
recomputes deliberately, but two rows landing on the same new key is a reason
to stop and report, never a reason to merge or delete.
"""

import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.dedupe import build_dedupe_key  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'repair_dedupe_keys.py'


class TestRepairScriptSafety(unittest.TestCase):
    """Static guarantees about what the migration is allowed to do."""

    def setUp(self):
        self.source = SCRIPT.read_text(encoding='utf-8')
        self.code = self._executable_code(self.source)

    @staticmethod
    def _executable_code(source):
        """Source with docstrings and comments stripped.

        The script's own docstring quotes the bad pattern to explain it, so a
        naive substring search matches the explanation rather than the code.
        """
        import ast
        import io
        import tokenize

        out = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.NL):
                continue
            if token.type == tokenize.STRING:
                continue  # includes every docstring
            out.append(token.string)
        ast.parse(source)  # the script must at least be valid Python
        return ' '.join(out)

    def test_script_exists(self):
        self.assertTrue(SCRIPT.exists())

    def test_recomputes_deliberately_not_with_the_or_fallback(self):
        # `job.dedupe_key or build_dedupe_key(job)` is exactly the behaviour
        # that let stale keys survive; the migration must not reuse it.
        self.assertNotRegex(self.code, r'dedupe_key\s+or\s+build_dedupe_key')

    def test_never_deletes_or_merges_jobs(self):
        for forbidden in ('db.session.delete', 'delete ( )',
                          'duplicate_of_id =', 'is_hidden = True'):
            self.assertNotIn(forbidden, self.code,
                             f'repair script must not {forbidden!r}')

    def test_only_writes_the_dedupe_key_column(self):
        assignments = set(re.findall(r'^\s*job\.(\w+)\s*=(?!=)', self.source, re.M))
        self.assertEqual(assignments, {'dedupe_key'}, assignments)

    def test_dry_run_is_the_default(self):
        self.assertIn('--apply', self.source)
        self.assertIn('if not args . apply', self.code)

    def test_backs_up_before_writing(self):
        self.assertIn('def backup_database', self.code)
        apply_section = self.source[self.source.index("print('\\nApplying...')"):]
        self.assertIn('backup_database()', apply_section)

    def test_reports_collisions(self):
        self.assertIn('Collision groups', self.source)


class TestCollisionDetection(unittest.TestCase):
    """The identity rules the repair depends on."""

    def _key(self, title, company='Acme', location='Boston, MA'):
        return build_dedupe_key(
            {'company': company, 'title': title, 'location': location})

    def test_bracketed_specialisations_get_distinct_keys(self):
        # The TikTok case: these are different openings and must not collide.
        titles = [
            'Machine Learning Engineer Graduate (TikTok-Data-Search-Visual Search) - 2027 Start',
            'Machine Learning Engineer Graduate (TikTok-Data-Search-Basic Ranking) - 2027 Start',
            'Machine Learning Engineer Graduate (TikTok-Data-Search-Recommendation) - 2027 Start',
        ]
        keys = [self._key(t, company='TikTok', location='CA') for t in titles]
        self.assertEqual(len(set(keys)), len(keys), keys)

    def test_identical_postings_still_collapse(self):
        self.assertEqual(
            self._key('Data Engineer, New Grad'),
            self._key('Data Engineer (New Graduate)'))

    def test_different_roles_do_not_collapse(self):
        self.assertNotEqual(self._key('Data Engineer'), self._key('Data Analyst'))

    def test_different_cities_do_not_collapse(self):
        self.assertNotEqual(
            self._key('Data Engineer', location='Boston, MA'),
            self._key('Data Engineer', location='Austin, TX'))

    def test_a_missing_identity_yields_no_key_rather_than_a_shared_one(self):
        # Returning a constant here would collapse every unidentifiable row.
        self.assertIsNone(build_dedupe_key({'company': '', 'title': ''}))

    def test_seniority_variants_share_a_key_but_are_unreachable_via_scraping(self):
        # Documented trade-off: level tokens are stripped for identity, so
        # these collide. Senior titles are dropped by the scoring gate before
        # storage, so a senior posting can never absorb a new-grad one.
        from services.ranking import score_job

        self.assertEqual(self._key('Senior Data Engineer'), self._key('Data Engineer'))
        result = score_job({
            'title': 'Senior Data Engineer', 'company': 'Acme',
            'location': 'Boston, MA', 'description': 'x' * 400,
            'source': 'greenhouse',
        })
        self.assertFalse(result['match']['eligible'],
                         'a senior title must never reach storage')


if __name__ == '__main__':
    unittest.main()
