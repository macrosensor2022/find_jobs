# JobTracker — Full-Time New Grad Job Command Center

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Flask-3.0-green.svg" alt="Flask">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

A personal, OPT-oriented job-search **command center** for **full-time new-grad /
early-career** Data Engineering, Analytics and BI roles. Internship and co-op
titles are hard-dropped by default.

Open **Today** every morning to answer one question: *"What should I apply to
today?"*

Repo: [macrosensor2022/find_jobs](https://github.com/macrosensor2022/find_jobs) ·
Architecture notes: [docs/ARCHITECTURE_AUDIT.md](docs/ARCHITECTURE_AUDIT.md)

---

## What it does

Every few hours it scrapes a set of job sources, normalizes and de-duplicates
the results, scores each posting against your profile, and ranks what is worth
your time today.

It optimizes for **legitimate, fresh, relevant, actionable** jobs — not job
count. A run that stores 2,000 mostly-stale listings is worse than one that
stores 80 you could actually apply to.

### Rules the system holds itself to

- **Never invent a job, company, contact, apply URL, or posting date.** Unknown
  is stored and displayed as unknown.
- **Freshness is measured against the source posting date**, computed against
  *now*. Re-discovering a 45-day-old posting does not make it new — it updates
  `last_seen` and nothing else.
- **Apply is only enabled for a link we fetched and read.** Blocked, redirected,
  unreachable and unchecked links all say so plainly and stay disabled.
- **A source that cannot run says why.** Missing API key, switched off, or
  failing — never "succeeded with 0 jobs".
- **Sponsorship status is evidence-backed** (green / yellow / red / unknown).
  No evidence means `unknown`.

---

## Architecture

```
Sources ──► JobScraperManager ──► normalize ──► filter/score ──► dedupe ──► SQLite
                    │                                                        │
              per-source isolation                                           ▼
              (one failure never                                    services/ranking
               stops the run)                            match · opportunity · quality
                                                          priority · role family
                                                        skill gaps · industry · golden
                                                                             │
                                                                             ▼
                                                          verification ──► Flask API
                                                                             │
                                                                             ▼
                                          Today · Jobs · Applications · Insights · Scraper
```

| Layer | Technology |
|-------|------------|
| Backend | Python 3.9+, Flask 3.0, SQLAlchemy |
| Frontend | HTML5, CSS3, vanilla JavaScript |
| Database | SQLite (WAL mode; PostgreSQL-ready) |
| Scraping | Requests, BeautifulSoup4, Selenium (NUWorks only) |
| Scheduling | APScheduler, with a timer-thread fallback |

Key modules:

| Path | Responsibility |
|------|----------------|
| `services/ranking.py` | The single scoring entry point (`score_job` → `apply_to_model`) |
| `services/rescore.py` | The single rescoring path — CLI, startup and scheduler share it |
| `services/briefing.py` | Today ranking, realistic-apply filters, source health |
| `services/freshness.py` | Posting-age buckets; never invents a posting date |
| `services/maintenance.py` | Recomputes derived freshness columns against *now* |
| `services/source_health.py` | Which sources can run, and why the others cannot |
| `services/verification.py` | Apply-URL checks: verified / dead / blocked / redirected |
| `backend/scrape_state.py` | One process-wide scrape slot, shared by UI and scheduler |

---

## Requirements

- Python 3.9 or newer (developed on 3.13)
- pip
- Chrome or Brave — **only** if you enable NUWorks
- No API keys required to get started

---

## Installation

### Windows (PowerShell)

```powershell
cd "D:\find_jobs"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # optional — the app runs without it
python run.py
```

> If `Activate.ps1` is blocked, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

### macOS / Linux

```bash
cd find_jobs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Then open **http://localhost:8080**.

The database is created automatically at `instance/jobs.db` on first run;
schema migrations and derived-field backfills run at startup and are idempotent.

---

## Configuration

Everything is optional — see `.env.example` for the annotated full list.

### Job age policy

All ages are measured against the **source posting date**, never against scrape
or rediscovery time.

| Setting | Default | Meaning |
|---------|---------|---------|
| `MAX_JOB_AGE_DAYS` | 30 | Past this, a stored posting is treated as expired |
| `TODAY_MAX_AGE_DAYS` | 14 | Today only recommends postings younger than this |
| `WATCH_MAX_AGE_DAYS` | 21 | Still worth watching, not a Today headline |
| `SCRAPE_MAX_AGE_DAYS` | 14 | Sources drop older listings at ingest |

### Sources

| Source | Type | Key needed | Default |
|--------|------|------------|---------|
| GitHub New Grad (SimplifyJobs) | JSON feed | No | on |
| GitHub Internships | JSON feed | No | **off** |
| Company ATS (Greenhouse / Lever / Ashby) | API | No | on |
| RemoteOK / The Muse / Remotive / Arbeitnow | API | No | on |
| Adzuna | API | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | on if keyed |
| JSearch (RapidAPI) | API | `JSEARCH_API_KEY` | on if keyed |
| LinkedIn | Web | No | **off** (slow) |
| NUWorks (Northeastern) | Web + Duo 2FA | credentials | **off** |

Toggle any of them with `ENABLE_<SOURCE>=false`. A source that is off, or whose
key is missing, appears on the Scraper and Insights pages as **Disabled** with
the reason — it never reports a misleading "0 jobs".

### Scoring

```
FINAL = (0.70 x candidate_match + 0.30 x opportunity) x quality_multiplier
```

`config/settings.py` holds the candidate profile (`EDUCATION`, `EXPERIENCE`,
`PROFILE_SKILLS`, `ROLE_TIERS`, `TARGET_STATES` / `EXCLUDED_STATES`) that the
matching engine consumes. Change weights or skills there, then re-score:

```bash
python scripts/rescore_all.py
```

---

## Running a scrape

**From the UI:** open **Scraper**, pick your sources, press **Start Scraping**.
Progress streams into the page; the UI stays usable while it runs. Starting a
second scrape while one is in flight returns "a scrape is already running"
rather than launching a competing one.

**From the CLI:**

```bash
python run_scrape.py
```

Each run records a `SearchRun` plus one `SourceRun` per source, capturing
discovered / matched / new / duplicates / rejected / duration / errors. That is
what the source-health tables read from.

---

## Scheduler

Runs inside the Flask process. Default: every 3 hours.

```env
SCHEDULE_ENABLED=true
SCHEDULE_MODE=interval     # or 'daily'
SCHEDULE_INTERVAL_HOURS=3
SCHEDULE_HOUR=7            # used when SCHEDULE_MODE=daily
SCHEDULE_TIMEZONE=America/New_York
```

> **The scheduler only runs while `python run.py` is running.** Close that
> terminal and nothing is scraped until you start it again. It does not depend
> on a browser tab being open, but it does depend on the server process. For
> scraping that survives a reboot, use Task Scheduler (Windows) or cron to run
> `python run_scrape.py` on your own interval.

Scheduled and manual runs share one scrape slot, so they cannot overlap. Live
status, last run, and last failure are on `GET /api/schedule`.

---

## Testing

```bash
# Full suite
python -m pytest tests -q

# Or with plain unittest
python -m unittest discover -s tests -q

# One module
python -m pytest tests/test_freshness_policy.py -v

# JS syntax check after frontend edits
node --check frontend/static/js/app.js
```

Tests run against a throwaway SQLite file in your temp directory, never against
`instance/jobs.db` — importing `backend.app` runs migrations and backfills, so
the test run is isolated automatically (`config/settings.py::_under_test`).

Set `DATABASE_URL` explicitly if you want to point the suite somewhere specific.

---

## Maintenance scripts

```bash
python scripts/rescore_all.py             # re-score everything with the current engine
python scripts/rescore_all.py --missing   # only rows missing newer score fields
python scripts/rescore_all.py --limit 50  # try a small batch first
python scripts/dedupe_existing.py         # collapse duplicates already stored
python scripts/inspect_jobs.py            # inspect what is in the database
```

---

## Troubleshooting

**"No fresh opportunities" on Today.**
Today is scoped to postings newer than `TODAY_MAX_AGE_DAYS` (14) that classify
into a target role tier. Run a scrape, widen your location preferences in
**Profile**, or raise `TODAY_MAX_AGE_DAYS`. Older matches are still on **Jobs**.

**A source shows "Disabled".**
It is switched off (`ENABLE_<SOURCE>=false`) or missing its API key. The Scraper
page names the exact environment variable. Add it to `.env` and restart.

**Apply buttons say "Unable to verify".**
The apply link has not been checked yet, or the check was blocked. Press
**Verify** on the card. Apply is deliberately only enabled for links we fetched
and read — the button is never enabled on a guess.

**"database is locked".**
SQLite runs in WAL mode with a 30-second busy timeout, and only one scrape runs
at a time. If it persists, another process is holding the database — close other
copies of the app, or raise `SQLITE_BUSY_TIMEOUT_SECONDS`.

**A scrape is slow.**
The Muse and other full-feed boards are fetched once per run and filtered
locally. If a run still drags, lower the source count or raise
`SOURCE_TIME_BUDGET_SECONDS`.

**SSL errors on Windows.**
`truststore` is installed on Python 3.10+ to use the OS certificate store, and
scrapers fall back to an unverified retry for a single request. Corporate
proxies may still need `REQUESTS_CA_BUNDLE` pointed at your CA file.

**Scheduler never fires.**
Check `GET /api/schedule` → `status.running`. It only runs while `run.py` is
running.

---

## Project structure

```
find_jobs/
├── backend/          # Flask app, models, scheduler, scrape coordination
├── config/           # settings.py — candidate profile + all tunables
├── frontend/         # templates + static (CSS / JS)
├── scrapers/         # source adapters, manager, matcher, metro/LCA
├── services/         # scoring, ranking, freshness, verification, health
├── scripts/          # rescore / dedupe / inspection helpers
├── tests/            # unit + integration tests
├── run.py            # start the server (+ scheduler)
├── run_scrape.py     # one-off scrape from the CLI
└── README.md
```

---

## License

MIT — see [LICENSE](LICENSE).
