# JobTracker — Architecture Audit & Upgrade Plan

**Date:** 2026-08-25  
**Repo:** https://github.com/macrosensor2022/find_jobs  
**Rule:** Upgrade in place. Do not rebuild. Never fabricate jobs or apply URLs.

---

## CURRENT STATE

JobTracker is already a personal OPT / full-time new-grad command center — not a greenfield board.

### What already works (keep)

| Area | Status |
|------|--------|
| Flask + SQLite + migrations | Working |
| Multi-source scrapers (GitHub Simplify, ATS, RemoteOK, Muse, Remotive, Adzuna, JSearch, LinkedIn opt-in) | Working |
| Background scrape + `/api/scrape/status` | Working |
| Daily scheduler (APScheduler / thread fallback, 7:00 America/New_York) | Working |
| Explainable scoring (`services/matching`, opportunity, quality, ranking) | Working |
| Sponsorship evidence (green/yellow/red/unknown — no guessing) | Working |
| Role tiers + experience gate (FT new-grad; intern/senior hard-drop) | Working |
| Dedup + provenance fields (`external_id`, `application_url`, verify timestamps) | Working |
| **Today** briefing (`/api/briefing`) — “what should I apply to today?” | Working |
| Apply gated on `application_url_status == verified` | Working |
| Prepare application drafts (no auto-submit) | Working |
| Applications + follow-ups + watchlist + insights | Working |
| Location preferences in Profile UI | Working |
| NUWorks disabled (`NUWORKS_ENABLED=false`) | Working |

### Product principle already encoded

**Quality × Relevance × Freshness × Application probability** — not job count.  
`FINAL ≈ 70% match + 30% opportunity`, scaled by quality. Apply Now never appears for invented URLs.

---

## PROBLEMS (gaps to close — not a rewrite)

1. **Apply links mostly unverified** until someone clicks Verify → most cards show “Unable to verify”.
2. **Daily run didn’t auto-verify** top jobs after scrape (now wired).
3. **Dual score story** — legacy `opt_fit_score` / `rank_score` vs new `candidate_match` / `final_score` (UI should prefer new).
4. **`Job.application_status` vs `Application` table** can diverge.
5. **Stale docs** (`docs/PROJECT_OVERVIEW.md` still intern-era in places).
6. **SQLite lock risk** under concurrent scrape + UI.
7. **Adzuna/JSearch** silent-skip without `.env` keys (documented, not a bug).
8. Empty `excluded_states = []` was ignored (`[] or defaults`) — fixed.

---

## PROPOSED ARCHITECTURE (keep Flask)

```
UI (Today / Jobs / Apps / Insights / Scraper / Profile)
        ↓
Flask REST API
        ↓
Services (match, opportunity, quality, verify, briefing, prep, analytics)
        ↓
JobScraperManager → source adapters
        ↓
SQLite (Job + Application + SearchRun + Preferences + …)
```

Background: one scheduler path = same code as “Run search now”.

---

## IMPLEMENTATION PLAN

| Phase | Focus | Status |
|-------|--------|--------|
| 1 | Audit (this doc) | Done |
| 2 | Profile / NUWorks off / location prefs | Largely done in tree |
| 3 | Transparent match + sponsorship + role tiers | Largely done |
| 4 | Provenance + URL verify + source metrics | Done + **batch verify added** |
| 5–6 | Daily ranking + Today dashboard | Done |
| 7 | Application prep | Done |
| 8 | Notifications | Done (dashboard); email optional |
| 9 | Outcome analytics / watchlist | Done |
| 10 | Tests + performance + cleanup | In progress |

### Just shipped in this pass

- Post-scrape + daily-run **batch URL verification** (`services/batch_verify.py`)
- `POST /api/jobs/verify-top`
- Fix empty `excluded_states` falsy bug
- `VERIFY_TOP_N` config

### Still recommended (non-destructive)

- Rescore old rows: `python scripts/rescore_all.py`
- Prefer `final_score` everywhere in Jobs list defaults
- Unify Mark Applied → always upsert `Application` + follow-up
- Quarantine orphan NUWorks JS
- Refresh README / PROJECT_OVERVIEW
- Optional SMTP notifications

---

## ACCEPTANCE MAPPING

| Criterion | How we meet it |
|-----------|----------------|
| Real jobs only | Scrapers + no fabricated rows |
| No fake apply URLs | Verify or show Unable to verify |
| Dedup | `services/dedupe.py` |
| Filter senior / intern | Experience gate + FT mode |
| Transparent scores | WHY / GAPS / breakdown on Job |
| Sponsorship evidence | Stored with source text |
| Freshness buckets | `services/freshness.py` |
| Daily search | Scheduler 7am ET |
| Top jobs first | Today briefing |
| Prep then apply | Prepare modal; human submits |
| Track + follow-ups | Applications API |
| Source failure isolation | Per-source try/except in manager |

**North star UI:** open **Today** → see top jobs → Verify links / Run search now → Prepare → Apply (only if verified) → Mark Applied.
