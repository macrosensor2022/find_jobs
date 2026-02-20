# API Documentation

JobTracker provides a RESTful API for all operations. All endpoints return JSON.

## Base URL

```
http://localhost:8080/api
```

## Authentication

Currently, no authentication is required (local use only).

---

## Jobs

### List Jobs

```http
GET /api/jobs
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| page | int | Page number (default: 1) |
| per_page | int | Items per page (default: 20) |
| source | string | Filter by source (linkedin, remoteok, etc.) |
| location | string | Filter by location (partial match) |
| status | string | Filter by application status |
| is_favorite | boolean | Filter favorites only |
| search | string | Search in title, company, description |
| date_filter | string | today, week, or month |
| show_hidden | boolean | Include hidden jobs |

**Response:**

```json
{
  "jobs": [
    {
      "id": 1,
      "title": "Data Science Intern",
      "company": "Tech Corp",
      "location": "New York, NY",
      "description": "...",
      "job_url": "https://...",
      "source": "remoteok",
      "match_score": 75,
      "is_favorite": false,
      "is_applied": false,
      "application_status": "not_applied",
      "date_posted": "2026-02-19T10:00:00",
      "created_at": "2026-02-19T12:00:00"
    }
  ],
  "total": 100,
  "page": 1,
  "per_page": 20,
  "total_pages": 5
}
```

### Get Job Details

```http
GET /api/jobs/{id}
```

**Response:**

```json
{
  "id": 1,
  "title": "Data Science Intern",
  "company": "Tech Corp",
  "location": "New York, NY",
  "description": "Full job description...",
  "job_url": "https://...",
  "source": "remoteok",
  "salary_min": 25,
  "salary_max": 35,
  "job_type": "internship",
  "is_remote": true,
  "match_score": 75,
  "matched_skills": ["python", "machine learning", "sql"],
  "is_favorite": false,
  "is_applied": false,
  "application_status": "not_applied",
  "notes": "",
  "date_posted": "2026-02-19T10:00:00",
  "created_at": "2026-02-19T12:00:00"
}
```

### Update Job

```http
PUT /api/jobs/{id}
```

**Request Body:**

```json
{
  "is_favorite": true,
  "application_status": "applied",
  "notes": "Applied via company website"
}
```

**Response:**

```json
{
  "message": "Job updated successfully",
  "job": { ... }
}
```

### Add Job Manually

```http
POST /api/jobs
```

**Request Body:**

```json
{
  "title": "ML Engineer Intern",
  "company": "AI Startup",
  "location": "Remote",
  "description": "...",
  "job_url": "https://..."
}
```

### Delete/Hide Job

```http
DELETE /api/jobs/{id}
```

**Response:**

```json
{
  "message": "Job hidden successfully"
}
```

---

## Statistics

### Get Dashboard Stats

```http
GET /api/stats
```

**Response:**

```json
{
  "total_jobs": 150,
  "new_today": 12,
  "favorites": 25,
  "applied": 10,
  "by_source": {
    "remoteok": 50,
    "themuse": 40,
    "linkedin": 30,
    "nuworks": 20,
    "manual": 10
  },
  "by_status": {
    "not_applied": 140,
    "applied": 7,
    "interviewing": 2,
    "offer": 1,
    "rejected": 0
  }
}
```

---

## Scraper

### Start Scraping

```http
POST /api/scrape/start
```

**Request Body:**

```json
{
  "sources": ["remoteok", "themuse"],
  "keywords": ["Data Science Intern", "ML Intern"],
  "locations": ["New York", "Remote"],
  "min_match_score": 30
}
```

**Response:**

```json
{
  "message": "Scraping completed",
  "results": {
    "started_at": "2026-02-19T12:00:00",
    "completed_at": "2026-02-19T12:01:30",
    "total_new_jobs": 25,
    "total_matched_jobs": 45,
    "min_match_score": 30,
    "sources": {
      "remoteok": {
        "total_found": 100,
        "matched_jobs": 30,
        "new_jobs": 15,
        "errors": []
      },
      "themuse": {
        "total_found": 50,
        "matched_jobs": 15,
        "new_jobs": 10,
        "errors": []
      }
    }
  }
}
```

---

## NUWorks

### Start Login

```http
POST /api/nuworks/login/start
```

**Request Body:**

```json
{
  "username": "your.email@northeastern.edu",
  "password": "your_password"
}
```

**Response:**

```json
{
  "status": "waiting_duo",
  "message": "Please complete Duo 2FA in the browser window"
}
```

### Check Login Status

```http
GET /api/nuworks/login/check
```

**Response:**

```json
{
  "status": "logged_in",
  "message": "Successfully logged in"
}
```

### Scrape NUWorks Jobs

```http
POST /api/nuworks/scrape
```

### Close Session

```http
POST /api/nuworks/close
```

---

## Profile

### Get Profile

```http
GET /api/profile
```

### Update Profile

```http
PUT /api/profile
```

**Request Body:**

```json
{
  "name": "Your Name",
  "github_url": "https://github.com/username",
  "linkedin_url": "https://linkedin.com/in/username",
  "target_role": "Data Science Intern",
  "resume_path": "/path/to/resume.pdf"
}
```

---

## Error Responses

All errors return a JSON object:

```json
{
  "error": "Error message description"
}
```

**Common Status Codes:**

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 404 | Not Found |
| 500 | Internal Server Error |
