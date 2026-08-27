# JobTracker — Full-Time New Grad Job Command Center

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Flask-3.0-green.svg" alt="Flask">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

OPT-oriented personal job-search **command center** for **full-time new-grad / early-career** Data Engineering, Analytics, and BI. Co-op and internship titles are filtered out by default.

Open **Today** every morning to answer: *“What should I apply to today?”*  
Full architecture notes: [docs/ARCHITECTURE_AUDIT.md](docs/ARCHITECTURE_AUDIT.md).

Built with Flask + a responsive frontend. Repo: [macrosensor2022/find_jobs](https://github.com/macrosensor2022/find_jobs).

![Dashboard Preview](docs/dashboard-preview.png)

## Features

### Morning command center
- **Today briefing**: top ranked jobs, strong matches, follow-ups, notifications
- **Run search now** + scheduled daily scrape (default 7:00 AM America/New_York)
- **Apply Now** only after the stored application URL is live-verified (never invented)
- **Prepare application**: tailored drafts for review — you submit on the official site

### Job Aggregation
- **Multi-source scraping**: [SimplifyJobs GitHub new-grad lists](https://github.com/SimplifyJobs/New-Grad-Positions), ATS boards (Greenhouse/Lever/Ashby), RemoteOK, The Muse, Remotive, Arbeitnow, LinkedIn, Adzuna, JSearch
- **Background scrapes**: UI stays usable; poll `/api/scrape/status` while jobs land in the DB
- **Explainable match**: skills / responsibilities / experience / education / role / location / authorization + WHY / GAPS
- **OPT intelligence**: evidence-backed sponsorship status; E-Verify / LCA when loaded locally
- **Dedup + quality**: prefer official postings; demote stale / unverified listings

### Job Management
- Filter by match, sponsorship, location, source, verified apply URL, favorites, applied
- Applications tracker + follow-up reminders
- Company watchlist + outcome insights
- Freshness buckets (hot → stale)

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.9+, Flask 3.0, SQLAlchemy |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Database | SQLite (PostgreSQL-ready) |
| Scraping | Requests, BeautifulSoup4, Selenium (NUWorks) |

## Quick Start

### Prerequisites
- Python 3.9+
- pip
- Chrome/Brave (only if using NUWorks)

### Installation

```bash
git clone https://github.com/macrosensor2022/find_jobs.git
cd find_jobs

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # optional API keys
python run.py
```

Open **http://localhost:8080**

## Configuration

```env
# Optional Adzuna (~1000 free calls/month)
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
MAX_ADZUNA_CALLS=20

# Optional JSearch / RapidAPI
JSEARCH_API_KEY=
MAX_JSEARCH_CALLS=8

# NUWorks (optional)
NUWORKS_USERNAME=
NUWORKS_PASSWORD=
```

`config/settings.py` controls:
- `SEEKING_FULL_TIME_NEW_GRAD = True` — hard-drops intern/co-op titles
- `TARGET_STATES` / `EXCLUDED_STATES` (CA/WA/OR excluded)
- `GITHUB_SIMPLIFY_FEEDS` — SimplifyJobs listings.json URLs
- Profile skills / keywords for DE · Analytics · BI · Azure · SSIS

## Usage

1. Open **Scraper**
2. Keep **GitHub New Grad FT** checked (internships optional / off by default)
3. Pick DE / new-grad keywords and locations
4. **Start Scraping** — runs in the background; jobs auto-refresh
5. Review **Jobs** (last 7 days) sorted by rank / match

## Testing

```bash
# Unit tests (no server required)
python -m unittest tests.test_github_simplify tests.test_experience_filter tests.test_adzuna_jsearch tests.test_location_metro -v

# End-to-end API tests (server must be running)
python run.py   # other terminal
python -m tests.test_platform
```

## Recent Updates

- Full-time **new-grad** focus (co-op/intern hard-dropped)
- SimplifyJobs GitHub feeds (new-grad + optional intern lists)
- Async scrape + status polling; SSL hardenings for Windows
- Adzuna + JSearch budgeted APIs; ATS board fan-out
- Metro opportunity / LCA enrichment; experience gate
- Experience + GitHub scraper unit tests

## Project Structure

```
find_jobs/
├── backend/          # Flask app + models
├── config/           # settings.py
├── frontend/         # templates + static
├── scrapers/         # sources + matcher + metro/LCA
├── scripts/          # rescore / sample / metro helpers
├── tests/            # unit + platform tests
├── run.py
└── README.md
```

## Job Sources

| Source | Type | Auth | Notes |
|--------|------|------|-------|
| GitHub New Grad | JSON | No | SimplifyJobs [New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) |
| GitHub Intern | JSON | No | Optional — off by default |
| ATS (GH/Lever/Ashby) | API | No | Configured boards |
| RemoteOK / The Muse / Remotive | API | No | |
| Adzuna / JSearch | API | Free key | Optional |
| LinkedIn | Web | No | Slow; off by default |
| NUWorks | Web | Duo 2FA | Northeastern |

## License

MIT — see [LICENSE](LICENSE).

---

**Built for full-time new-grad DE / Analytics search (OPT)** · [github.com/macrosensor2022/find_jobs](https://github.com/macrosensor2022/find_jobs)
