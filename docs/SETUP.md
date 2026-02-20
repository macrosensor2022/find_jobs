# Setup Guide

This guide provides detailed instructions for setting up JobTracker on your system.

## System Requirements

- **Python**: 3.9 or higher
- **Operating System**: Windows 10/11, macOS, or Linux
- **Browser**: Chrome or Brave (for NUWorks scraping)
- **RAM**: 4GB minimum
- **Storage**: 100MB for application + database

## Installation Methods

### Method 1: Standard Installation

```bash
# Clone the repository
git clone https://github.com/macrosensor2022/find_jobs.git
cd find_jobs

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

### Method 2: Development Installation

```bash
# Clone with development dependencies
git clone https://github.com/macrosensor2022/find_jobs.git
cd find_jobs

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install with development tools
pip install -r requirements.txt
pip install pytest black flake8 mypy

# Run in development mode
python run.py
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required for NUWorks
NUWORKS_USERNAME=your.email@northeastern.edu
NUWORKS_PASSWORD=your_password

# Optional: Adzuna API for more job sources
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
```

### Database

The application uses SQLite by default. The database is automatically created on first run at `instance/jobs.db`.

To use PostgreSQL instead:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/jobtracker
```

### Port Configuration

The default port is 8080. To change it, edit `run.py`:

```python
app.run(port=YOUR_PORT)
```

## Verifying Installation

1. Start the server:
   ```bash
   python run.py
   ```

2. Check the console output:
   ```
   ============================================================
     Job Search Dashboard - Summer 2026 Co-op Search
   ============================================================
   
     Starting server...
     Open http://localhost:8080 in your browser
   ```

3. Open http://localhost:8080 in your browser

4. You should see the JobTracker dashboard

## Troubleshooting

### Port Already in Use

```bash
# Windows: Find process using port 8080
netstat -ano | findstr :8080

# Kill the process
taskkill /PID <PID> /F
```

### Database Migration Issues

If you see database schema errors after updating:

```bash
# Delete old database
rm instance/jobs.db

# Restart application (database recreates automatically)
python run.py
```

### Selenium/Chrome Issues

For NUWorks scraping:

```bash
# Ensure Chrome or Brave is installed
# Selenium 4.6+ handles driver management automatically

# If issues persist, install webdriver-manager
pip install webdriver-manager
```

## Next Steps

- [Usage Guide](USAGE.md) - Learn how to use JobTracker
- [API Documentation](API.md) - API endpoints reference
- [Contributing](CONTRIBUTING.md) - How to contribute
