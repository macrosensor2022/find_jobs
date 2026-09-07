"""Configuration precedence: env > stored preference > code default.

The stored ``schedule`` preference used to win unconditionally. It is seeded
once on first run, so after that ``SCHEDULE_ENABLED=true`` in ``.env`` did
nothing — verified at the time by starting the app with it set and watching
the scheduler stay off.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.scheduler import _load_schedule  # noqa: E402
from config.settings import Config, env_is_set  # noqa: E402


class FakePreference:
    """Stands in for the Preference model without a database."""

    stored = None

    class _Query:
        def filter_by(self, **kwargs):
            self.key = kwargs.get('key')
            return self

        def first(self):
            if self.key != 'schedule' or FakePreference.stored is None:
                return None
            row = FakePreference()
            row.parsed = FakePreference.stored
            return row

    query = _Query()


class EnvTestCase(unittest.TestCase):
    """Restores every environment variable the test touched."""

    def setUp(self):
        self._saved = {}
        FakePreference.stored = None

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        FakePreference.stored = None

    def set_env(self, name, value):
        self._saved.setdefault(name, os.environ.get(name))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class TestEnvIsSet(EnvTestCase):
    def test_unset_is_false(self):
        self.set_env('JOBTRACKER_PRECEDENCE_PROBE', None)
        self.assertFalse(env_is_set('JOBTRACKER_PRECEDENCE_PROBE'))

    def test_set_is_true(self):
        self.set_env('JOBTRACKER_PRECEDENCE_PROBE', 'anything')
        self.assertTrue(env_is_set('JOBTRACKER_PRECEDENCE_PROBE'))

    def test_blank_counts_as_unset(self):
        # A commented-out or emptied line in .env must not shadow a preference.
        self.set_env('JOBTRACKER_PRECEDENCE_PROBE', '   ')
        self.assertFalse(env_is_set('JOBTRACKER_PRECEDENCE_PROBE'))

    def test_config_exposes_the_helper(self):
        self.set_env('JOBTRACKER_PRECEDENCE_PROBE', 'x')
        self.assertTrue(Config.env_overrides('JOBTRACKER_PRECEDENCE_PROBE'))


class TestSchedulePrecedence(EnvTestCase):
    def test_stored_preference_applies_when_env_is_unset(self):
        for name in Config.SCHEDULE_ENV_KEYS.values():
            self.set_env(name, None)
        FakePreference.stored = {'enabled': False, 'interval_hours': 12}
        schedule = _load_schedule(FakePreference, Config)
        self.assertFalse(schedule['enabled'])
        self.assertEqual(schedule['interval_hours'], 12)

    def test_explicit_env_beats_the_stored_preference(self):
        # The exact regression: preference says off, .env says on.
        self.set_env('SCHEDULE_ENABLED', 'true')
        FakePreference.stored = {'enabled': False}

        class Cfg(Config):
            SCHEDULE_ENABLED = True

        self.assertTrue(_load_schedule(FakePreference, Cfg)['enabled'])

    def test_env_override_is_per_key_not_all_or_nothing(self):
        self.set_env('SCHEDULE_ENABLED', 'true')
        self.set_env('SCHEDULE_INTERVAL_HOURS', None)
        FakePreference.stored = {'enabled': False, 'interval_hours': 9}

        class Cfg(Config):
            SCHEDULE_ENABLED = True

        schedule = _load_schedule(FakePreference, Cfg)
        self.assertTrue(schedule['enabled'], 'env-set key uses env')
        self.assertEqual(schedule['interval_hours'], 9, 'unset key uses preference')

    def test_code_default_applies_with_no_env_and_no_preference(self):
        for name in Config.SCHEDULE_ENV_KEYS.values():
            self.set_env(name, None)
        FakePreference.stored = None
        schedule = _load_schedule(FakePreference, Config)
        self.assertEqual(schedule['mode'], Config.SCHEDULE_MODE)
        self.assertEqual(schedule['timezone'], Config.SCHEDULE_TIMEZONE)

    def test_sources_are_not_env_controlled_so_the_preference_wins(self):
        FakePreference.stored = {'sources': ['remoteok']}
        self.assertEqual(
            _load_schedule(FakePreference, Config)['sources'], ['remoteok'])

    def test_every_schedule_key_has_a_documented_env_name(self):
        schedule = _load_schedule(FakePreference, Config)
        # 'sources' is intentionally preference-only (edited from the UI).
        for key in schedule:
            if key == 'sources':
                continue
            self.assertIn(key, Config.SCHEDULE_ENV_KEYS, key)


class TestFollowupDaysPrecedence(EnvTestCase):
    def test_env_name_is_registered(self):
        from backend.app import _PREFERENCE_ENV_KEYS
        self.assertEqual(_PREFERENCE_ENV_KEYS.get('followup_days'), 'FOLLOWUP_DAYS')

    def test_explicit_env_beats_the_stored_preference(self):
        from backend.app import _preference

        self.set_env('FOLLOWUP_DAYS', '3,9')
        # Fallback is what Config parsed from the environment.
        self.assertEqual(_preference('followup_days', [3, 9]), [3, 9])

    def test_preference_applies_when_env_is_unset(self):
        # Without the env guard short-circuiting, this reaches the database,
        # so it needs an app context (and the isolated test DB).
        from backend.app import _preference, app

        self.set_env('FOLLOWUP_DAYS', None)
        with app.app_context():
            self.assertEqual(_preference('followup_days', [7, 14]), [7, 14])


if __name__ == '__main__':
    unittest.main()
