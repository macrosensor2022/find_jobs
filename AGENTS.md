# AGENTS.md

Repo: **find_jobs** — JobTracker, a personal full-time job-search "command center" (new-grad Data Engineering / Analytics) that scrapes job boards, scores each posting for candidate fit, and ranks them.

## Commands

- Run server: `python3 run.py` (Flask, port from `Config.PORT`, usually 8080).
- Full test suite (plain pytest/unittest): `python3 -m unittest discover -s tests -q`
- JS syntax check: `node --check frontend/static/js/app.js`
- Re-score every stored job after changing weights/skills/sponsorship:
  `python3 scripts/rescore_all.py` (not the app's background thread, which only fills rows with `final_score IS NULL`).
- Run the app's scheduler/background: started by `run.py` via `backend.scheduler`.

## Architecture (services/)

- `services/ranking.score_job(...)` is the single scoring entry point and returns a `result` dict consumed by `apply_to_model(job_model, result)`. It persists: candidate/opportunity/quality/final scores, match breakdown/reasons/gaps/risks, freshness bucket, location/role blocked flags, sponsorship status, **and Phase 2/6/7/8/9/10 fields**: `application_priority_score`, `application_recommendation`, `application_readiness_score`, `application_effort_estimate`, `role_family`, `hidden_fit`, `skill_gap_matrix`.
- `services/priority.py` — Phase 2/9/10: `application_priority`, `recommendation_for` (returns **uppercase** actions `APPLY NOW`/`APPLY`/`WATCH`/`SKIP`), `application_readiness` (score capped ≤ 94), `application_effort` (returns band strings `5-10 min`/`10-20 min`/`20-40 min`/`40+ min`, or `None` when nothing provided).
- `services/role_family.py` — Phase 6/7: `classify_family` → 7 families incl. `DATA_AUTOMATION` + `hidden_fit`; `is_data_automation` excludes QA-only (Selenium) roles.
- `services/skill_gaps.py` — Phase 8: `skill_gap_matrix(job)` returns `MATCHED`/`PARTIAL`/`MISSING` per required skill. **Requires description ≥ `Config.MIN_DESCRIPTION_CHARS`** (200) or returns a thin-description note. PARTIAL uses `_PARTIAL_BRIDGES`. A skill present in the profile (any proficiency) is MATCHED, so `dbt` with proficiency 1 is MATCHED, not PARTIAL.
- `services/analytics.py` — `build_analytics`, plus `employer_radar(db, Job, days, limit)` and `search_health(db, Job, SearchRun)`. NOTE: use `from sqlalchemy import case` (import `case`, not `func.case`) for conditional sums.
- `services/briefing.why_hidden(job)` — explains listing filters off real stored fields.

## Backend / API

- `backend/app.py` wires routes incl. `/api/analytics/employer-radar`, `/api/analytics/market-skills`, `/api/search/health`, `/api/jobs/<id>/why-hidden`, and `/api/jobs` filters `min_priority`, `recommendation`, `min_readiness`, `sort_by=priority` (priority sorts via `application_priority_score.desc().nullslast()`).
- `backend/models.py` holds `Job` (new columns for the Phase fields), `SearchRun`, etc. New DB columns are added via the column-map + `_ensure_columns` migration in `backend/app.py`; existing rows are not backfilled automatically.

## Frontend

- `frontend/static/js/app.js` — card renderers. `recommendationBadge(job)` + `FRESHNESS_UI` (now HOT/FRESH/RECENT/AGING/OLD/STALE). Cards show recommendation badge, readiness %, effort, role family, hidden-fit pill, competition, and a `skillMatrixBlock`. `renderJobList` delegates to `renderSmartJobList`.
- CSS for those in `frontend/static/css/command-center.css`.

## Testing conventions

- Tests import services with `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` so they run under plain `python -m unittest` (no custom harness needed). The project runner injects a nonstandard import path; plain pytest works now.
- Keep effort/readiness/recommendation assertions aligned to the *actual* returns (uppercase actions, band strings, ≤94 readiness cap).

## Gotchas

- `application_effort` banding: do NOT invert the bands (`40+` → `'40+ min'`, `20-40` → `'20-40 min'`, `10-20` → `'10-20 min'`).
- Always `node --check` app.js after editing the frontend.
- Never invent applicant counts/competition — `competition_signal` is only set from legitimate source data via the updater.