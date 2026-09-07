# AGENTS.md

Repo: **find_jobs** — JobTracker, a personal full-time job-search "command center" (new-grad Data Engineering / Analytics) that scrapes job boards, scores each posting for candidate fit, and ranks what to apply to today.

## Commands

- Run server: `python run.py` (Flask + scheduler, port from `Config.PORT`, usually 8080).
- Full test suite: `python -m pytest tests -q` (or `python -m unittest discover -s tests -q`).
- JS syntax check: `node --check frontend/static/js/app.js`
- Re-score every stored job after changing weights/skills/sponsorship:
  `python scripts/rescore_all.py` (`--missing` for only rows lacking newer fields).
- One-off scrape from the CLI: `python run_scrape.py`

## Non-negotiable invariants

These encode bugs that were fixed and must not come back.

1. **Freshness is derived from `date_posted` against *now*.** Never from
   `date_scraped`, `first_seen` or `last_seen`. The stored
   `freshness_bucket` / `freshness_hours` columns exist for SQL filtering and go
   stale between refreshes — read paths use `Job.live_freshness()` /
   `services.maintenance.live_freshness`, and `refresh_freshness` rebuilds the
   columns at startup, after every scrape, and from `rescore_all.py`.
2. **Rediscovery only moves `last_seen`.** `_merge_duplicate` must never touch
   `date_scraped` or `first_seen`. Seeing a job again is evidence it is still
   open, not that it was reposted.
3. **`date_posted` is the source's posting date or NULL.** Never substitute
   scrape time or a `date_updated` value — those go in `source_updated_at`.
   `date_posted_origin` records which it was (`feed` / `unknown`).
4. **"New" means `first_seen` within the window**, never `date_scraped`.
5. **Apply is enabled only for `application_url_status == 'verified'`.** The
   other states (`dead`, `blocked`, `redirected`, `unverified`, `unknown`) each
   say what was found and keep Apply disabled. Never construct an apply URL.
6. **A source that cannot run reports `disabled` with a reason**, never
   "success with 0 jobs". `services/source_health.py` resolves this; reasons
   name the missing config *key*, never its value.
7. **Nothing is fabricated** — jobs, companies, contacts, URLs, posting dates,
   applicant counts, sponsorship claims. Unknown is stored and shown as unknown.

## Architecture (services/)

- `services/ranking.score_job(...)` is the single scoring entry point; it returns a `result` dict consumed by `apply_to_model(job_model, result)`.
- `services/rescore.py` is the single **re**scoring path — the CLI script, the app's startup task, and any backfill all go through `rescore_jobs`. Adding a scored field means adding it to `needs_rescore` too, or existing rows silently keep NULL.
- `services/briefing.py` — `today_rank_score` (Today's ordering: freshness × relevance × actionability, deliberately *not* `ORDER BY final_score`), `realistic_filters` (age measured on `date_posted` against a cutoff computed now), `source_metrics` (per-source health covering every registered source, not just ones that ran).
- `services/maintenance.py` — `refresh_freshness`, `backfill_seen_timestamps`, `live_freshness`.
- `services/source_health.py` — enablement + health labels. `STATUS_EMPTY` ("ran, found nothing") is deliberately distinct from `STATUS_DISABLED` and `STATUS_FAILED`.
- `services/application_sync.py` — `Application` is canonical; `Job.application_status` / `is_applied` / `applied_date` are derived. Every status write goes through `sync_job_from_application` or `sync_application_from_job`.
- `services/verification.py` — `verify_url` returns verified / dead / blocked / redirected / unverified / unknown. Only `verified` is in `APPLYABLE_STATUSES`.
- `services/priority.py` — `recommendation_for` returns **uppercase** actions (`APPLY NOW`/`APPLY`/`WATCH`/`SKIP`); `application_readiness` caps at 94; `application_effort` returns band strings (`5-10 min` … `40+ min`) or `None`.
- `services/role_family.py` — `classify_family` → 7 families incl. `DATA_AUTOMATION` + `hidden_fit`; `is_data_automation` excludes QA-only (Selenium) roles.
- `services/skill_gaps.py` — `skill_gap_matrix(job)` returns `MATCHED`/`PARTIAL`/`MISSING`. Requires description ≥ `Config.MIN_DESCRIPTION_CHARS` (200) or returns a thin-description note.
- `services/analytics.py` — `build_analytics`, `employer_radar`, `search_health`. Use `from sqlalchemy import case` (not `func.case`).

## Scrapers

- `Config.FULL_FEED_SOURCES` lists boards that ignore the keyword argument and return one full feed (`remoteok`, `arbeitnow`, `themuse`). The manager fetches these **once** per run and filters locally via `_filter_by_keywords`. Looping keywords re-downloaded the same payload 12× — The Muse alone took >10 minutes. **Remotive is not in this list**: it passes the keyword to the API as a server-side `search` param, so one keyword-less call returns a narrower set.
- `scrape_source` returns `status` / `rejected_breakdown` / `duration_seconds`; `_record_source_run` persists them. One source failing never stops the run.
- `_filter_and_score` sets `self._last_rejections` — a per-reason counter the Scraper page reads.

## Backend / API

- `backend/scrape_state.py` holds one process-wide scrape slot. Both `/api/scrape/start` and the scheduler call `begin()`; the loser gets `ScrapeInProgress` (409 / skip). Do not add a third path that scrapes without claiming it.
- `backend/scheduler.py::start` is idempotent; `status()` reports running / next run / last run / last failure.
- API errors return JSON via the `HTTPException` + `Exception` handlers — never HTML, never a traceback.
- `Job.to_dict(summary=True)` truncates descriptions for list endpoints; the detail route sends the full text.
- `backend/models.py::_iso` attaches UTC to naive datetimes before serializing. Without it `new Date()` reads them as local time and every timestamp renders as "Just now".
- New DB columns go in the column-map in `_migrate_add_columns`; existing rows are not backfilled automatically.

## Frontend

- `frontend/static/js/app.js` — `freshnessChip` (live posting age) and `discoveryChip` (first-seen, labelled as discovery) are separate on purpose. `parseApiDate` repairs a missing timezone defensively.
- `renderSourceHealth` must keep showing *why* a source produced nothing.
- CSS in `frontend/static/css/command-center.css`. Wide tables need both `max-width: 100%` and `min-width: 0` on their wrapper or they push the page sideways on mobile.
- NUWorks JS is dormant (no markup, never initialized) but the backend routes are live — see the comment above `initNUWorks`.

## Testing conventions

- Tests import services with `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` so they run under plain `python -m unittest`.
- `config/settings.py::_under_test` points `DATABASE_URL` at a temp file when a test runner is detected, and `Config.TESTING_MODE` suppresses the startup background tasks. Importing `backend.app` runs migrations and backfills, so **without this the suite rewrites `instance/jobs.db`**. Setting `DATABASE_URL` explicitly always wins.
- Keep effort/readiness/recommendation assertions aligned to the *actual* returns (uppercase actions, band strings, ≤94 readiness cap).

## Gotchas

- `application_effort` banding: do NOT invert the bands (`40+` → `'40+ min'`).
- Always `node --check app.js` after editing the frontend.
- Never invent applicant counts — `competition_signal` is set only from legitimate source data via the updater.
- SQLite runs in WAL with a 30s busy timeout (pragmas applied per-connection in `backend/app.py`). Keep transactions short in the scrape path.
