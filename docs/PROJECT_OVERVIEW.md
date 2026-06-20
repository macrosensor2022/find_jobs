# JobTracker — OPT Redesign Progress

**Document type:** Technical overview + implementation progress  
**Project path:** `d:\find_jobs`  
**Branch:** `feature/opt-redesign`  
**Last updated:** June 20, 2026

---

## 1. What Is JobTracker?

**JobTracker** is a full-stack job aggregator that automatically scrapes multiple job boards, scores each listing against a user-defined skill profile, removes duplicates, stores results in a database, and presents them in a dark-themed single-page dashboard where users can filter, favorite, and track applications.

**One-line value:** *Scrape → match → dedupe → enrich → store → display → track.*

---

## 2. The Redesign — From Intern Search to OPT Command Center

The app is being transformed from a **summer internship/co-op finder** into an **OPT-focused full-time job command center** for a December 2027 graduate targeting:

- **Primary lane:** Data Engineering / BI / Data Science / AI-NLP
- **Primary locations:** Boston, Portland ME, broad US, Remote
- **Immigration-aware features:** E-Verify lookup, H-1B background data, sponsorship screen detection, OPT runway tracking

### Key principles:
- H-1B data is **background intelligence only** — never a hard filter
- E-Verify/LCA data is ingested **locally** from downloaded CSVs (no live scraping)
- Never invent employer matches — return "unknown" when confidence is low
- No legal advice copy anywhere in the UI
- NUWorks is **excluded** from this redesign

---

## 3. Technology Stack

| Layer | Technology |
|-------|-----------|
| Web framework | Flask 3.x (Python) |
| Database | SQLite via SQLAlchemy ORM (`instance/jobs.db`) |
| Frontend | Vanilla JavaScript SPA + HTML + CSS (no build step) |
| Scraping (APIs/HTML) | `requests` + `BeautifulSoup` |
| Scraping (authenticated) | `Selenium` (NUWorks portal — excluded from redesign) |
| Fuzzy matching | `rapidfuzz` (employer name matching) |
| Config | `config/settings.py` + `.env` (via `python-dotenv`) |
| Entry point | `python run.py` → serves on `0.0.0.0:8080` |

---

## 4. Project Structure

```
d:\find_jobs\
├── backend/
│   ├── app.py              # Flask app + HTTP routes + migration function
│   └── models.py           # SQLAlchemy models (Job, SearchLog, UserProfile,
│                           #   EVerifyEmployer, SponsorHistory)
├── config/
│   └── settings.py         # Keywords, skills, locations, screen patterns,
│                           #   OPT thresholds
├── frontend/
│   ├── static/css/style.css
│   ├── static/js/app.js    # SPA logic + API client
│   └── templates/index.html
├── scrapers/
│   ├── base_scraper.py          # Abstract base (HTTP/SSL/retry)
│   ├── linkedin_scraper.py      # Full-time, entry-level, past week
│   ├── remoteok_scraper.py      # 30-day window, USA filter
│   ├── themuse_scraper.py       # Entry Level only, 30-day window
│   ├── arbeitnow_scraper.py     # 30-day window, strict USA filter
│   ├── remotive_scraper.py      # Remote jobs, USA filter
│   ├── adzuna_scraper.py        # Present but NOT wired in
│   ├── nuworks_scraper.py       # Selenium + Duo 2FA (excluded)
│   ├── profile_matcher.py       # Skill scoring + sponsorship screen +
│   │                            #   OPT fit score
│   ├── sponsorship_data.py      # Company normalization, employer lookup
│   │                            #   (single + batch), CSV/XLSX loaders
│   └── job_scraper_manager.py   # Orchestrates scrape → enrich → DB
├── data/                    # Local E-Verify/H-1B CSVs (gitignored)
├── docs/
│   ├── PROJECT_OVERVIEW.md  # This file
│   └── data_sources.md      # E-Verify & H-1B data source docs
├── tests/
│   ├── test_platform.py     # Pre-existing integration tests
│   └── test_sponsorship.py  # 46 unit tests for OPT features
├── instance/jobs.db         # Created at runtime
├── requirements.txt
└── run.py
```

---

## 5. What Has Been Built (Phases 1–3.5) ✅

### Phase 1 — Data Layer for OPT Sponsorship Intelligence

**Commit:** `ff397f4`

**New database tables:**

| Table | Purpose |
|-------|---------|
| `everify_employer` | E-Verify participating employer data (name, normalized name, city, state) |
| `sponsor_history` | H-1B LCA history (employer, fiscal year, LCA count, approvals, denials, median wage) |

**New columns on `Job` model (8):**

| Column | Type | Purpose |
|--------|------|---------|
| `is_everify` | Boolean | Employer participates in E-Verify |
| `opt_field_related` | Boolean | match_score ≥ 40% (relevant to OPT field) |
| `sponsorship_screen` | Boolean | Posting contains "will not sponsor" / "US citizen only" |
| `h1b_lca_count` | Integer | Employer's H-1B LCA filings |
| `wage_level` | Integer | Prevailing wage level from LCA data |
| `employer_match_conf` | Float | Confidence of employer name match (0.0–1.0) |
| `freshness_hours` | Integer | Hours since job was posted |
| `opt_fit_score` | Integer | Composite OPT viability score (0–100) |

**New columns on `UserProfile` model (4):**

| Column | Type | Purpose |
|--------|------|---------|
| `grad_date` | Date | Expected graduation date |
| `opt_start_date` | Date | OPT employment start date |
| `stem_eligible` | Boolean | Eligible for STEM OPT extension |
| `unemployment_days` | Integer | Cumulative OPT unemployment days |

**New module `scrapers/sponsorship_data.py`:**
- `normalize_company_name()` — strips legal suffixes (Inc, LLC, Corp), punctuation, leading "The"
- `lookup_employer()` — exact-then-fuzzy match against E-Verify/H-1B tables using `rapidfuzz`
- CSV loaders for E-Verify and H-1B LCA datasets
- CLI: `python -m scrapers.sponsorship_data --load-everify <path>`

**Migration:** Idempotent `_migrate_add_columns()` in `app.py` runs on startup — safely adds new columns to existing databases via `ALTER TABLE ADD COLUMN`.

---

### Phase 2 — Config + Matcher/Screen Detection + Scraper Retargeting

**Commit:** `54d16f2`

**`config/settings.py` — complete retarget:**

| Setting | Old value | New value |
|---------|-----------|-----------|
| `SEARCH_KEYWORDS` | 30+ intern/co-op terms | 28 full-time/new-grad terms (Data Engineer, BI Engineer, ML Engineer, etc.) |
| `DEFAULT_TARGET_ROLE` | "Data Science / ML / Data Engineering Intern" | "Data Engineer / BI Engineer / Data Scientist (Full-time, New Grad)" |
| `PROFILE_MATCHER_SKILLS` | ~40 skills, intern=20-25 weight | 83 skills, full-time terms=12-15, intern demoted to 5 |
| `PROFILE_MATCHER_NEGATIVE_KEYWORDS` | senior, staff, etc. | Added: security clearance (-15), us citizen only (-15) |

**New config values:**

| Setting | Value | Purpose |
|---------|-------|---------|
| `OPT_FIELD_MATCH_MIN` | 40 | match_score threshold for opt_field_related |
| `FRESHNESS_FAST_HOURS` | 24 | "Apply fast" badge threshold |
| `SPONSORSHIP_SCREEN_PATTERNS` | 14 regex patterns | Detect "will not sponsor", "US citizen only", clearance requirements |
| `SEARCH_KEYWORDS_INTERN` | 9 terms | Toggleable intern set for interim searches |

**`scrapers/profile_matcher.py` — two new methods:**

1. **`detect_sponsorship_screen(title, description)`** — scans text against 14 compiled regex patterns; returns `True` for dealbreaker language
2. **`compute_opt_fit_score(match_score, is_everify, sponsorship_screen, opt_field_related)`** — composite score:
   - Base = match_score
   - +15 if E-Verify employer
   - +5 if field-related (match_score ≥ 40%)
   - Capped at ≤20 if sponsorship_screen detected (dealbreaker)
   - H-1B data intentionally excluded from scoring (background only)

**Scraper changes:**

| Scraper | Change |
|---------|--------|
| LinkedIn | `f_JT='I'` → `'F'` (full-time), `f_TPR='r86400'` → `'r604800'` (past week), removed 48h hard cutoff |
| Arbeitnow | `MAX_AGE_DAYS` 3 → 30 |
| RemoteOK | `MAX_AGE_DAYS` 3 → 30 |
| TheMuse | `MAX_AGE_DAYS` 3 → 30, levels: `['Internship', 'Entry Level']` → `['Entry Level']` |
| base_scraper | Default `job_type`: `'internship'` → `'full-time'` |

**`scrapers/job_scraper_manager.py` — OPT enrichment pipeline:**

New `_enrich_job_with_opt_data()` method runs for every new job before saving:
1. `lookup_employer()` → sets `is_everify`, `h1b_lca_count`, `wage_level`, `employer_match_conf`
2. `detect_sponsorship_screen()` → sets `sponsorship_screen` flag
3. Sets `opt_field_related` = match_score ≥ 40%
4. `compute_opt_fit_score()` → sets `opt_fit_score`
5. Computes `freshness_hours` from `date_posted`

---

### Phase 2.5 — SSL Fix + Location Matching

**Commit:** `de207cb`

**SSL:** `_build_ssl_context()` now tries three strategies in order:
1. `truststore` (OS native trust store) — smoke-tested with real HTTPS request
2. `certifi` (Mozilla CA bundle) — smoke-tested against a scraper target URL
3. `verify=False` (local-dev fallback) — when Python 3.13's strict validation rejects certs

**Location matching:** Added "United States", "USA", "worldwide", "global" to `TARGET_LOCATIONS` and the manager's location alias map so API scrapers don't silently drop US/remote jobs.

---

### Phase 3 — Backend API Extensions + LCA XLSX Loader

**Commit:** `99b40f7`

**Extended `/api/jobs` with OPT filters:**

| Query param | Behavior |
|-------------|----------|
| `sponsorship_screen=true\|false` | Filter by sponsorship screen flag |
| `opt_field_related=true` | Only field-related jobs (match_score ≥ 40%) |
| `min_opt_fit=<int>` | Minimum OPT fit score |
| `max_freshness=<int>` | Maximum freshness_hours |
| `sort_by=opt_fit_score\|match_score\|freshness` | New sort modes (default remains date) |

**New endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/runway` | GET | Computes OPT employment timeline from `UserProfile` dates — days remaining, STEM extension end date, unemployment days used/remaining |
| `/api/sponsorship/refresh` | POST | Re-runs employer lookup + sponsorship screen detection on all visible jobs (backfill after loading E-Verify/H-1B data) |

**Extended `/api/profile` PUT:**
- Now accepts `grad_date`, `opt_start_date`, `stem_eligible`, `unemployment_days` with ISO date parsing and type coercion

**Fixed `DELETE /api/jobs/<id>`:**
- Default behavior changed to **soft-hide** (`is_hidden = True`)
- Hard delete available via `?hard=true` query param

**Rewrote `--load-lca` CLI in `sponsorship_data.py`:**
- Reads DOL LCA Disclosure XLSX files via `openpyxl` in read-only mode
- Aggregates ~210k rows into ~30k unique employers (by normalized name)
- Stores LCA count, approval/denial tallies, and median wage per employer
- Fixed CLI database path to use the main app's `instance/jobs.db`

**Config changes:**

| Setting | Value | Purpose |
|---------|-------|---------|
| `LINKEDIN_LOCATIONS` | 5 entries (Boston, NYC, Portland ME, US, Remote) | Caps LinkedIn crawl to prevent 150+ page fetches |

**Other changes:**
- Added `openpyxl` to `requirements.txt`
- Fixed Remotive scraper robustness (error handling, response parsing)
- Frontend `app.js` carryover fixes from Phase 2 work

---

### Phase 3.5 — Pipeline Verification, Fuzzy Match Fix, Frontend Rebrand

**Commit:** `8968831`

**End-to-end pipeline verification (LCA → lookup → enrichment → jobs):**
- Confirmed 30,171 rows in `sponsor_history` (FY2026 DOL LCA Disclosure data)
- 29,114 of 30,171 rows have `prevailing_wage_level` populated
- `wage_level` chain verified at every link: schema → loader → lookup → enrichment → API

**Verified `lookup_employer()` for major employers:**

| Company | h1b_lca_count | median_wage | wage_level | match_type |
|---------|--------------|-------------|------------|------------|
| Google | 3,058 | $194,000 | 1 | exact |
| Amazon | 5,347 | $155,000 | 1 | fuzzy (tie-broken by LCA count) |
| Microsoft | 2,915 | $180,710 | 1 | exact |

**Bug fix — fuzzy scorer (`token_sort_ratio` → `token_set_ratio`):**
- **Problem:** `token_sort_ratio("amazon", "aaon") = 80` matched AAON (2 LCAs) instead of Amazon.com Services LLC (5,347 LCAs). Short company names failed to match their official DOL filing names because extra words in the candidate penalized the score.
- **Fix:** Switched to `token_set_ratio` which correctly handles subset matching ("amazon" ⊂ "amazon com services" = 100).

**Bug fix — fuzzy tie-breaking:**
- **Problem:** When multiple candidates tie at the same fuzzy score (e.g. "Amazon Advertising" and "Amazon.com Services LLC" both at 100), `extractOne` picked arbitrarily.
- **Fix:** Use `process.extract(limit=10)`, collect all tied names, then pick the employer with the highest `lca_count`.

**New `batch_lookup_employers()` function:**
- Pre-loads all E-Verify and SponsorHistory data once, caches fuzzy results per unique normalized name
- `/api/sponsorship/refresh` rewired to use batch lookup
- Performance: ~57s for 1,317 jobs (vs. HTTP timeout with per-job lookup)

**Post-refresh stats (1,317 visible jobs):**

| Metric | Count |
|--------|-------|
| `h1b_lca_count` populated | 1,008 |
| `wage_level` populated | 998 |
| Both populated | 998 |
| `sponsorship_screen = True` | 3 |
| `opt_fit_score` populated | 1,317 |

**Frontend rebrand to OPT full-time focus:**

| Element | Before | After |
|---------|--------|-------|
| Page title | "Job Search Dashboard — Summer/Fall Internships" | "JobTracker — OPT Full-Time Job Command Center" |
| Sidebar subtitle | "Summer/Fall Internship Search" | "OPT Full-Time Job Search" |
| Scraper keywords | Data Science Intern, ML Intern, SDE Intern, etc. | Data Engineer, BI Engineer, Data Scientist, ML Engineer, New Grad variants |
| Season Focus section | "Summer Internship" / "Fall Internship" checkboxes | Removed |
| Scraper sources | Included NUWorks with Duo 2FA login | NUWorks removed (excluded from redesign) |
| Location layout | Low Competition / High Competition tiers | Primary (Boston, Portland ME, NYC, Remote, Broad US) + Additional |
| Source filter dropdown | Had NUWorks option | Replaced with Manual |
| Profile default role | "Data Science / ML / Data Engineering Intern" | "Data Engineer / BI Engineer / Data Scientist (Full-time, New Grad)" |
| Source chart colors | ZipRecruiter, Runway, NUWorks | RemoteOK, TheMuse, Remotive, Arbeitnow |
| Server banner | "Summer 2026 Co-op Search" | "OPT Full-Time Job Command Center" |

---

### Tests

**46 unit tests** in `tests/test_sponsorship.py`, all passing:

| Test class | Count | Covers |
|-----------|-------|--------|
| `TestNormalizeCompanyName` | 13 | Legal suffix stripping, punctuation, edge cases |
| `TestLookupEmployer` | 9 | Exact match, fuzzy match, no match, None/empty, fuzzy tie-break by LCA count |
| `TestBatchLookupEmployers` | 4 | Exact match, unknown, returns all names, dedupes normalized names |
| `TestSchemaCreation` | 3 | New tables and columns exist after migration |
| `TestSponsorshipScreen` | 8 | US citizen, no-sponsorship, clearance, clean posting, HTML, None |
| `TestComputeOptFitScore` | 9 | Base passthrough, E-Verify bonus, field bonus, screen cap, bounds |

---

## 6. What's Next (Phases 4–5) 🔜

### Phase 4 — Frontend OPT Intelligence UI

**Goal:** Surface the OPT data that's already flowing through the backend into visible UI elements.

| Change | Details |
|--------|---------|
| **OPT Runway Widget** | Visual countdown showing days remaining on OPT, STEM extension timeline, unemployment days used |
| **Smart Job Cards** | Badges: E-Verify ✓, sponsorship screen ⚠️, freshness ("new"), OPT fit score bar, H-1B LCA count |
| **New Filters** | Dropdowns/checkboxes for sponsorship_screen, opt_field_related, OPT fit score range, freshness |
| **Sort by OPT Fit** | Default sort changes from date to `opt_fit_score` descending |
| **Dashboard Stats** | Show OPT-specific aggregates: jobs with E-Verify, screened out count, average fit score |

### Phase 5 — Polish

| Change | Details |
|--------|---------|
| **Update README.md** | Document the OPT features, E-Verify/H-1B data loading, new endpoints |
| **Finalize data_sources.md** | Add exact column mappings, refresh cadence, troubleshooting |
| **Seed profile** | Pre-populate `UserProfile` with grad_date=2027-12, stem_eligible=True |
| **Test fixtures** | Add integration tests for new API filters and runway calculation |

---

## 7. How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Start the app
python run.py
# → Open http://localhost:8080

# Run tests (46 tests)
python -m pytest tests/test_sponsorship.py -v

# Load E-Verify data (optional — download CSV first)
python -m scrapers.sponsorship_data --load-everify data/everify_employers.csv

# Load H-1B LCA data (XLSX from DOL disclosure)
python -m scrapers.sponsorship_data --load-lca data/LCA_Disclosure_Data_FY2026_Q2.xlsx

# Re-clear and reload (if data is stale)
python -m scrapers.sponsorship_data --clear --load-lca data/LCA_Disclosure_Data_FY2026_Q2.xlsx

# Backfill OPT fields on existing jobs (after loading new data)
# via API:  POST http://localhost:8080/api/sponsorship/refresh
# or direct:  python -c "from backend.app import app; ..."
```

---

## 8. Architecture Diagram

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Job Boards  │────▶│   Scrapers   │────▶│  Profile Matcher  │
│  (LinkedIn,  │     │  (5 sources) │     │  (83 skills,      │
│   RemoteOK,  │     └──────────────┘     │   14 screen       │
│   TheMuse,   │                          │   patterns)        │
│   Arbeitnow, │                          └────────┬───────────┘
│   Remotive)  │                                   │
└─────────────┘                                    ▼
                                          ┌──────────────────┐
┌─────────────┐                           │  OPT Enrichment   │
│  E-Verify / │                           │  - employer lookup │
│  H-1B CSVs  │──▶ sponsorship_data.py ──▶│  - screen detect   │
│  (local)    │                           │  - opt_fit_score   │
└─────────────┘                           │  - freshness_hours │
                                          └────────┬───────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │   SQLite (jobs.db) │
                                          │   Job + SearchLog  │
                                          │   + UserProfile    │
                                          │   + EVerify/Sponsor│
                                          └────────┬───────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │   Flask API        │
                                          │   /api/jobs        │
                                          │   /api/profile     │
                                          │   /api/runway      │
                                          │   /api/sponsorship │
                                          │   /api/scrape      │
                                          └────────┬───────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │   Vanilla JS SPA   │
                                          │   Dashboard, Cards, │
                                          │   Filters, Tracking │
                                          └──────────────────┘
```

---

## 9. Commit History (feature/opt-redesign)

| Hash | Phase | Summary |
|------|-------|---------|
| `ff397f4` | 1 | Data layer: new tables, OPT columns, sponsorship_data module, migration |
| `54d16f2` | 2 | Retarget to full-time, sponsorship screen, OPT fit score, scraper updates |
| `de207cb` | 2.5 | SSL fallback fix (truststore→certifi→unverified), location matching fix |
| `99b40f7` | 3 | Backend API extensions (OPT filters, runway, refresh), LCA XLSX loader, LinkedIn cap |
| `8968831` | 3.5 | Fix fuzzy matching (token_set_ratio, tie-break by LCA count), batch_lookup_employers, frontend rebrand to OPT full-time, 46 tests |

---

*End of document.*
