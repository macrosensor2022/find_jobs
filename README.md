# JobTracker - Internship & Co-op Job Search Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Flask-3.0-green.svg" alt="Flask">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

A modern, full-stack job search aggregator designed for students seeking internships and co-op positions. Built with Flask backend and a beautiful dark-themed responsive frontend.

![Dashboard Preview](docs/dashboard-preview.png)

## Features

### Job Aggregation
- **Multi-source scraping**: Aggregate jobs from RemoteOK, The Muse, Arbeitnow, LinkedIn, Adzuna, and NUWorks
- **API-first approach**: Uses official APIs where available for reliable data collection
- **Profile matching**: Intelligent scoring system that matches jobs to your skills (0-100%)
- **Duplicate detection**: Automatically prevents duplicate job entries

### Job Management
- **Smart filtering**: Filter by source, location, date, and application status
- **Favorites**: Star jobs you're interested in for quick access
- **Application tracking**: Track your application pipeline (Applied → Interviewing → Offer)
- **Notes**: Add personal notes to any job posting

### Modern UI/UX
- **Dark theme**: Easy on the eyes for long job search sessions
- **Responsive design**: Works on desktop, tablet, and mobile
- **Real-time updates**: Instant feedback on actions
- **Keyboard shortcuts**: Power user features for efficiency

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.9+, Flask 3.0, SQLAlchemy |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Database | SQLite (easily switchable to PostgreSQL) |
| Scraping | Requests, BeautifulSoup4, Selenium |

## Quick Start

### Prerequisites
- Python 3.9 or higher
- pip (Python package manager)
- Chrome/Brave browser (for NUWorks scraping)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/macrosensor2022/find_jobs.git
   cd find_jobs
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment** (optional)
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Run the application**
   ```bash
   python run.py
   ```

6. **Open your browser**
   ```
   http://localhost:8080
   ```

## Configuration

### Environment Variables

Create a `.env` file in the root directory:

```env
# NUWorks credentials (Northeastern University)
NUWORKS_USERNAME=your.email@northeastern.edu
NUWORKS_PASSWORD=your_password

# Adzuna API (optional - get free key at https://developer.adzuna.com/)
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key

# Resume path for profile matching
RESUME_PATH=C:/path/to/your/resume.pdf
```

### Profile Matching

The profile matcher uses weighted keywords to score job relevance. Edit `scrapers/profile_matcher.py` to customize:

```python
self.skills = {
    'python': 15,        # High weight for Python
    'machine learning': 15,
    'data science': 15,
    'intern': 20,        # Boost for internship roles
    'co-op': 25,
    # Add your skills...
}
```

## Usage

### Scraping Jobs

1. Navigate to the **Scraper** tab
2. Select job sources (RemoteOK, The Muse recommended)
3. Choose keywords and locations
4. Set minimum match score (30% recommended)
5. Click **Start Scraping**

### NUWorks (Northeastern Students)

NUWorks requires Duo 2FA authentication:

1. Enter your Northeastern email and password
2. Click **Start Login** - a browser window opens
3. Complete Duo authentication on your phone
4. Click **I Completed Duo**
5. Click **Scrape NUWorks Jobs**

### Managing Jobs

- **Star**: Click the star icon to favorite a job
- **Apply**: Click the external link to apply, then mark as "Applied"
- **Hide**: Remove uninteresting jobs from your feed
- **Notes**: Add notes about each opportunity

## Project Structure

```
find_jobs/
├── backend/
│   ├── app.py              # Flask application & routes
│   └── models.py           # SQLAlchemy database models
├── config/
│   └── settings.py         # Application configuration
├── frontend/
│   ├── static/
│   │   ├── css/style.css   # Styles
│   │   └── js/app.js       # Frontend JavaScript
│   └── templates/
│       └── index.html      # Main HTML template
├── scrapers/
│   ├── base_scraper.py     # Base scraper class
│   ├── remoteok_scraper.py # RemoteOK API scraper
│   ├── themuse_scraper.py  # The Muse API scraper
│   ├── linkedin_scraper.py # LinkedIn scraper
│   ├── adzuna_scraper.py   # Adzuna API scraper
│   ├── nuworks_scraper.py  # NUWorks with Selenium
│   ├── profile_matcher.py  # Job-profile matching
│   └── job_scraper_manager.py # Scraper orchestration
├── instance/               # SQLite database (auto-created)
├── .env.example           # Environment template
├── .gitignore
├── requirements.txt       # Python dependencies
├── run.py                 # Application entry point
└── README.md
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs` | GET | List jobs with filters |
| `/api/jobs/<id>` | GET | Get job details |
| `/api/jobs/<id>` | PUT | Update job (favorite, status) |
| `/api/jobs/<id>` | DELETE | Hide job |
| `/api/jobs` | POST | Add job manually |
| `/api/stats` | GET | Dashboard statistics |
| `/api/scrape/start` | POST | Start job scraping |
| `/api/profile` | GET/PUT | User profile |

## Job Sources

| Source | Type | Auth Required | Status |
|--------|------|---------------|--------|
| RemoteOK | API | No | ✅ Working |
| The Muse | API | No | ✅ Working |
| LinkedIn | Web | No | ⚠️ Limited |
| Adzuna | API | Yes (free) | ✅ Working |
| NUWorks | Web | Yes (Duo 2FA) | ✅ Working |
| Indeed | RSS | No | ❌ Deprecated |

## Troubleshooting

### Port 5000 blocked
Windows sometimes blocks port 5000. The app defaults to port 8080:
```bash
# In run.py, change port:
app.run(port=8080)
```

### NUWorks browser not opening
Ensure Chrome or Brave is installed:
```bash
# Install selenium and webdriver-manager
pip install selenium webdriver-manager
```

### Database errors after updates
Delete the database and restart:
```bash
rm instance/jobs.db
python run.py
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [RemoteOK](https://remoteok.com) for their public API
- [The Muse](https://www.themuse.com) for their job API
- [Font Awesome](https://fontawesome.com) for icons
- [Inter Font](https://rsms.me/inter/) for typography

---

**Built with ❤️ for the Summer 2026 Co-op Search**  
*Last updated: February 2026*
