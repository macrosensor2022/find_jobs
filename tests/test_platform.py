#!/usr/bin/env python
"""
End-to-end platform tests.
Run with: python -m tests.test_platform
Requires the Flask server to be running (python run.py).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080")
TIMEOUT = 10
SCRAPE_TIMEOUT = 120  # Scrape can take a while

passed = 0
failed = 0
errors = []


def ok(name):
    global passed
    passed += 1
    print(f"  [PASS] {name}")


def fail(name, msg):
    global failed, errors
    failed += 1
    errors.append((name, msg))
    print(f"  [FAIL] {name}: {msg}")


def test_stats():
    """GET /api/stats returns totals and breakdowns."""
    try:
        r = requests.get(f"{BASE}/api/stats", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for key in ("total_jobs", "applied_jobs", "favorite_jobs", "new_today", "by_source", "by_status"):
            if key not in data:
                fail("stats structure", f"missing key: {key}")
                return
        ok("GET /api/stats")
    except Exception as e:
        fail("GET /api/stats", str(e))


def test_jobs_list():
    """GET /api/jobs returns paginated jobs with correct shape."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 5}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for key in ("jobs", "total", "pages", "current_page", "has_next", "has_prev"):
            if key not in data:
                fail("jobs list structure", f"missing key: {key}")
                return
        jobs = data["jobs"]
        if jobs:
            job = jobs[0]
            for field in ("id", "title", "company", "source", "date_posted", "date_scraped"):
                if field not in job:
                    fail("job object structure", f"missing field: {field}")
                    return
        ok("GET /api/jobs (list)")
    except Exception as e:
        fail("GET /api/jobs", str(e))


def test_jobs_filter_source():
    """GET /api/jobs?source=X returns only jobs from that source."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 50, "source": "remoteok"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for job in data["jobs"]:
            if job.get("source") != "remoteok":
                fail("jobs filter source", f"got source {job.get('source')} for job id {job.get('id')}")
                return
        ok("GET /api/jobs?source=remoteok")
    except Exception as e:
        fail("GET /api/jobs?source=...", str(e))


def test_jobs_filter_date():
    """GET /api/jobs?date_filter=today returns 200 and valid list."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 5, "date_filter": "today"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if "jobs" not in data:
            fail("jobs date_filter", "response missing jobs key")
            return
        ok("GET /api/jobs?date_filter=today")
    except Exception as e:
        fail("GET /api/jobs?date_filter=...", str(e))


def test_jobs_search():
    """GET /api/jobs?search=X returns 200 and list (keyword in title/company/description)."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 5, "search": "data"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if "jobs" not in data:
            fail("jobs search", "response missing jobs key")
            return
        ok("GET /api/jobs?search=...")
    except Exception as e:
        fail("GET /api/jobs?search=...", str(e))


def test_jobs_filter_location():
    """GET /api/jobs?location=X returns 200."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 5, "location": "Remote"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if "jobs" not in data:
            fail("jobs location filter", "response missing jobs key")
            return
        ok("GET /api/jobs?location=...")
    except Exception as e:
        fail("GET /api/jobs?location=...", str(e))


def test_job_detail():
    """GET /api/jobs/:id returns one job."""
    try:
        r = requests.get(f"{BASE}/api/jobs", params={"per_page": 1}, timeout=TIMEOUT)
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
        if not jobs:
            ok("GET /api/jobs/:id (no jobs to fetch)")
            return
        jid = jobs[0]["id"]
        r2 = requests.get(f"{BASE}/api/jobs/{jid}", timeout=TIMEOUT)
        r2.raise_for_status()
        job = r2.json()
        if job.get("id") != jid or "title" not in job or "company" not in job:
            fail("job detail", f"invalid response for id {jid}")
            return
        ok("GET /api/jobs/:id")
    except Exception as e:
        fail("GET /api/jobs/:id", str(e))


def test_profile():
    """GET /api/profile returns profile or empty."""
    try:
        r = requests.get(f"{BASE}/api/profile", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            fail("profile", "response is not a dict")
            return
        ok("GET /api/profile")
    except Exception as e:
        fail("GET /api/profile", str(e))


def test_config():
    """GET /api/config/locations and keywords return arrays."""
    try:
        r = requests.get(f"{BASE}/api/config/locations", timeout=TIMEOUT)
        r.raise_for_status()
        if not isinstance(r.json(), list):
            fail("config locations", "expected list")
            return
        r = requests.get(f"{BASE}/api/config/keywords", timeout=TIMEOUT)
        r.raise_for_status()
        if not isinstance(r.json(), list):
            fail("config keywords", "expected list")
            return
        ok("GET /api/config/locations and keywords")
    except Exception as e:
        fail("GET /api/config", str(e))


def test_scrape_and_match():
    """POST /api/scrape/start with minimal payload; then verify jobs match query."""
    try:
        payload = {
            "sources": ["remoteok"],
            "keywords": ["Data Science Intern"],
            "locations": ["Remote"],
            "min_match_score": 0,
        }
        r = requests.post(
            f"{BASE}/api/scrape/start",
            json=payload,
            timeout=SCRAPE_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if "results" not in data:
            fail("scrape/start response", "missing results")
            return
        results = data["results"]
        if "sources" not in results:
            fail("scrape/start results", "missing sources")
            return
        # Check remoteok in results
        if "remoteok" not in results["sources"]:
            fail("scrape/start sources", "remoteok not in results.sources")
            return
        ro = results["sources"]["remoteok"]
        if "error" in ro and ro["error"]:
            fail("scrape remoteok", ro["error"])
            return
        # Fetch jobs from API for this source and verify they exist and have expected fields
        r2 = requests.get(f"{BASE}/api/jobs", params={"source": "remoteok", "per_page": 20}, timeout=TIMEOUT)
        r2.raise_for_status()
        jobs_data = r2.json()
        jobs = jobs_data.get("jobs", [])
        for job in jobs[:5]:
            if job.get("source") != "remoteok":
                fail("scrape job source", f"job id {job.get('id')} has source {job.get('source')}")
                return
            if not job.get("title"):
                fail("scrape job title", f"job id {job.get('id')} has no title")
                return
        ok("POST /api/scrape/start and jobs match source")
    except requests.exceptions.Timeout:
        fail("scrape/start", "request timed out (scrape may be slow)")
    except Exception as e:
        fail("scrape/start", str(e))


def test_scrape_empty_locations_default():
    """POST /api/scrape/start with empty locations still runs (backend uses default)."""
    try:
        payload = {
            "sources": ["themuse"],
            "keywords": ["Data Analyst Intern"],
            "locations": [],
            "min_match_score": 0,
        }
        r = requests.post(
            f"{BASE}/api/scrape/start",
            json=payload,
            timeout=SCRAPE_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if "results" not in data or "sources" not in data["results"]:
            fail("scrape empty locations", "invalid response")
            return
        # Themuse is API-based; with empty locations we pass default in backend so no crash
        ok("POST /api/scrape/start with empty locations (uses default)")
    except requests.exceptions.Timeout:
        fail("scrape empty locations", "timeout")
    except Exception as e:
        fail("scrape empty locations", str(e))


def main():
    print(f"\nPlatform tests against {BASE}\n")
    test_stats()
    test_jobs_list()
    test_jobs_filter_source()
    test_jobs_filter_date()
    test_jobs_search()
    test_jobs_filter_location()
    test_job_detail()
    test_profile()
    test_config()
    test_scrape_and_match()
    test_scrape_empty_locations_default()
    print(f"\nTotal: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
