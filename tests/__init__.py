"""Test package bootstrap.

Importing ``backend.app`` runs migrations, backfills and a background rescore
against whatever database ``DATABASE_URL`` points at. Left alone that is the
real ``instance/jobs.db`` — running the suite would migrate and rewrite the
user's actual job data.

Pointing the tests at a throwaway file, and switching off the startup
background work, has to happen before any test module imports the app, so it
lives here at package-import time.
"""

import os
import tempfile

_TEST_DB = os.path.join(tempfile.gettempdir(), 'jobtracker_test.db')
os.environ.setdefault('DATABASE_URL', f'sqlite:///{_TEST_DB}')
os.environ.setdefault('JOBTRACKER_DISABLE_STARTUP_TASKS', '1')
os.environ.setdefault('SCHEDULE_ENABLED', 'false')
