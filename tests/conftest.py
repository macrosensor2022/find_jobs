"""Hermetic-suite guarantees.

Two things went wrong before this existed:

1. Importing ``backend.app`` runs migrations, backfills and a background
   rescore against whatever ``DATABASE_URL`` resolves to — by default the real
   ``instance/jobs.db``. Running the suite migrated and rewrote real job data.
2. ``tests/test_platform.py`` (now ``platform_check.py``) POSTed
   ``/api/scrape/start`` at whatever server happened to be on localhost:8080,
   so ``pytest`` triggered live scrapes that wrote 30 rows into the production
   database over one working session.

``config/settings.py::_under_test`` already redirects the database. This file
adds the second half: outbound HTTP is blocked outright, so a test that tries
to reach the network fails loudly instead of quietly depending on a server
that may or may not be running.

Both guards are belt-and-braces on purpose — either alone would have prevented
the incident, and neither is expensive.
"""

import os
import socket
import tempfile

import pytest

# Must be set before anything imports config.settings / backend.app.
os.environ.setdefault(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(tempfile.gettempdir(), 'jobtracker_test.db'),
)
os.environ.setdefault('JOBTRACKER_TEST', '1')
os.environ.setdefault('JOBTRACKER_DISABLE_STARTUP_TASKS', '1')
os.environ.setdefault('SCHEDULE_ENABLED', 'false')


class NetworkAccessAttempted(RuntimeError):
    """Raised when a test tries to open a socket to anywhere."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, request):
    """Fail any test that reaches the network.

    Opt out for a specific test with ``@pytest.mark.allow_network`` — nothing
    in the suite does today, and adding one should be a deliberate decision.
    """
    if request.node.get_closest_marker('allow_network'):
        return

    def _blocked(*args, **kwargs):
        raise NetworkAccessAttempted(
            'Outbound network access is blocked in the test suite. '
            'Use a fake/stub transport, or the Flask test client for API '
            'calls. See tests/conftest.py.'
        )

    # socket.socket.connect covers requests/urllib/httpx-sync; create_connection
    # is the fast path urllib3 uses.
    monkeypatch.setattr(socket.socket, 'connect', _blocked, raising=False)
    monkeypatch.setattr(socket.socket, 'connect_ex', _blocked, raising=False)
    monkeypatch.setattr(socket, 'create_connection', _blocked, raising=False)


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'allow_network: permit real outbound connections for this test',
    )


def pytest_report_header(config):
    return (
        f"jobtracker: DATABASE_URL={os.environ['DATABASE_URL']} "
        '(network blocked)'
    )
