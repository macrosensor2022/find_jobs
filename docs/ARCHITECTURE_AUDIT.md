# JobTracker — Architecture Audit & Upgrade Log

**Last pass:** 2026-09-07
**Repo:** https://github.com/macrosensor2022/find_jobs
**Rule:** Upgrade in place. Do not rebuild. Never fabricate jobs or apply URLs.

---

## CURRENT STATE

JobTracker is a personal OPT / full-time new-grad command center — not a
greenfield board. The 2026-09-07 pass audited the whole pipeline against real
data and fixed a cluster of correctness bugs around **time**.

### Architecture

```
Sources ──► JobScraperManager ──► normalize ──► score/filter ──► dedupe ──► SQLite
                    │                                                        │
              per-source isolation                                           ▼
              + enablement check                                    services/ranking
                                                         match · opportunity · quality
                                                          priority · role family
                                                        skill gaps · industry · golden
                                                                             │
                                            services/maintenance             ▼
                                            (freshness refresh)      verification
                                                                             │
                                                                             ▼
                                                                        Flask API
                                                                             │
                                          Today · Jobs · Applications · Insights · Scraper
```

One scrape slot (`backend/scrape_state.py`) is shared by the UI button and the
scheduler, so the two can never run concurrently.

---

## FIXED IN THE 2026-09-07 PASS

### The time cluster (the core defect)

Freshness was stored at scoring time and served raw. A job scored two weeks
earlier still reported `freshness_bucket = 'fresh'`, so the UI told the user a
14-day-old posting went up yesterday, and the "not stale" filter let it through.

Compounding it, `_merge_duplicate` bumped `date_scraped` on every rediscovery,
`briefing.new_today` counted `date_scraped >= 24h ago`, and the Today ranking
gave a +15 bonus for a recent `date_scraped`. A 45-day-old posting that was
re-seen today was therefore counted as new *and* boosted to the top.

| Fix | Where |
|-----|-------|
| Freshness computed against *now* from `date_posted` on every read | `Job.live_freshness`, `Job.to_dict` |
| Set-based refresh of the stored columns at startup / post-scrape / rescore | `services/maintenance.refresh_freshness` |
| Rediscovery moves `last_seen` only | `job_scraper_manager._merge_duplicate` |
| `new_today` counts `first_seen` | `services/briefing.build_briefing` |
| Today ranking keys off posting age; discovery bonus is small and uses `first_seen` | `services/briefing.today_rank_score` |
| Age filters compare `date_posted` to a cutoff computed now | `services/briefing.realistic_filters` |
| `date_updated` no longer stands in for `date_posted` | `github_simplify_scraper`, new `source_updated_at` column |
| Naive UTC datetimes serialized with a timezone | `backend/models._iso` |

The last one made every timestamp in the UI render as "Just now": a naive ISO
string is parsed by `new Date()` as local time, putting it hours in the future.

### Source health

Adzuna and JSearch have no API keys, returned zero jobs, and were recorded as
`status='success', jobs_discovered=0` — indistinguishable from a board that ran
fine and had nothing.

- `services/source_health.py` resolves enablement; disabled sources report the
  reason and name the missing config key (never its value).
- `SourceRun` gained `jobs_matched`, `jobs_rejected`, `rejected_breakdown`,
  `duration_seconds`, `message`; status now includes `empty` and `disabled`.
- Insights and Scraper surface all of it; the Scraper form disables sources
  that cannot run instead of offering them.

### Scraper performance

RemoteOK, Arbeitnow and The Muse use the keyword only to filter an
already-fetched feed, but the manager called them once per keyword — 12
identical downloads. The Muse (36 requests each) took **>10 minutes** per run.

Fetching once and filtering locally was verified to return the identical job
set (0 missed, 0 extra) in 1.9s vs 21.8s for RemoteOK. A full 8-source run went
from ~20 minutes to **34 seconds**. Remotive was deliberately excluded — it
passes the keyword to the API server-side.

The Muse also discarded every job already collected if any one of its 36
requests timed out; failures are contained per page now.

### Other fixes

| Problem | Fix |
|---------|-----|
| Running the test suite migrated and rewrote `instance/jobs.db` | `_under_test` points tests at a temp DB; `TESTING_MODE` suppresses startup tasks |
| 701/740 rows had `final_score` but no recommendation / industry / golden score | One rescore path (`services/rescore.py`); `needs_rescore` covers every scored field |
| `Job.application_status` and `Application.status` only agreed on APPLIED | `services/application_sync.py` — Application is canonical, job fields derived, startup reconcile |
| Marking a job applied from the Jobs page created no tracker entry or follow-up | Same sync, plus follow-up scheduling on that path |
| Follow-ups had no overdue/due-today split, no snooze or cancel | `/api/followups` buckets; `POST .../followup` takes `done`/`snoozed`/`cancelled` |
| Blocked and redirected apply links were reported as plain "unverified" | `verify_url` distinguishes them; only `verified` enables Apply |
| Verification budget spent on jobs the user was not looking at | `select_jobs_to_verify` orders by the Today ranking |
| API errors returned HTML | JSON error handlers; no stack traces in responses |
| `per_page=99999` serialized the whole table (2.3 MB) | Clamped to `MAX_PAGE_SIZE`; list responses truncate descriptions |
| `app.run(debug=True)` under `__main__` on a 0.0.0.0 bind | Opt-in via `FLASK_DEBUG=1` |
| `source_count` under-reported for multi-source jobs | `_merge_duplicate` seeds the set with the job's own source |
| Scheduler could start a scrape during a manual one | Shared scrape slot |
| Scheduler could be double-started | `start()` is idempotent |
| "Posted today" notifications persisted for days | Message states the posting date |
| Wide tables pushed the page sideways on mobile | Wrapper `max-width: 100%` + `min-width: 0` |

---

## VERIFIED IN THIS PASS

- 298 tests pass, 5 skip (they need live sponsorship data that is not committed).
- Full 8-source scrape: 384 discovered, 130 matched, 130 duplicates, 254
  rejected, 34s wall clock, 2 sources correctly reported disabled.
- All five views render with **0 console errors and 0 failed requests**;
  0px horizontal overflow at 390px wide.
- Application workflow driven end to end: verify → prepare → SHORTLISTED →
  APPLIED → INTERVIEW → OFFER, with the job row tracking each step.

---

## KNOWN LIMITATIONS

- **Adzuna and JSearch are off** — no API keys in this environment. They are
  reported as disabled rather than silently empty.
- **Sponsorship is `unknown` for nearly every job.** The evidence sources
  (E-Verify list, LCA disclosure) are not loaded; `everify_employer` is empty.
  Correct behaviour, but the sponsorship signal is not useful until loaded.
- **GitHub New Grad descriptions are stubs**, so those jobs carry
  "Provisional score: the posting text was not available" risk flags and thin
  skill matrices. Honest, but repetitive on the Today page.
- **`role_tier` is NULL for ~40% of stored jobs** — the classifier declines to
  guess. Those are excluded from Today by design and visible on Jobs.
- **The scheduler lives in the Flask process.** Nothing runs while `run.py` is
  stopped. Documented in the README; use Task Scheduler / cron with
  `run_scrape.py` if you need it to survive a reboot.
- **Dedupe merges seniority levels** — "Data Engineer" and "Data Engineer I" at
  one company in one city collapse to one row. Deliberate (level tokens are
  stripped for identity); covered by a test that documents the trade-off.

---

## ACCEPTANCE MAPPING

| Criterion | How we meet it |
|-----------|----------------|
| Real jobs only | Scrapers only; no synthetic rows anywhere |
| No fake apply URLs | Apply gated on `verified`; other states explain themselves |
| Honest freshness | Computed from `date_posted` against now, on every read |
| Rediscovery ≠ new | `first_seen` immutable; only `last_seen` moves |
| Dedup | `services/dedupe.py` — stable ID → URL → fingerprint |
| Filter senior / intern | Experience gate + FT mode + role classifier |
| Transparent scores | WHY / GAPS / RISKS + breakdown on every card |
| Sponsorship evidence | Stored with source text; `unknown` when absent |
| Source failure isolation | Per-source try/except + per-source run records |
| Disabled ≠ empty ≠ failed | Three distinct statuses, each with a reason |
| Daily search | Scheduler, 3-hourly by default, one slot shared with the UI |
| Prep then apply | Prepare modal; the human submits |
| Track + follow-ups | Applications API + overdue/due/upcoming buckets |

**North star UI:** open **Today** → see fresh, relevant, verified jobs →
Prepare → Apply (only if verified) → Mark Applied → follow up.
