import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from backend.models import db, Job, SearchLog, UserProfile, EVerifyEmployer, SponsorHistory
from config.settings import Config
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_job_data(data: dict, partial: bool = False) -> tuple:
    """Validate job data fields. Returns (is_valid, error_message)"""
    if not data:
        return False, "No data provided"
    
    # Required fields for new jobs
    required_fields = ['title', 'company']
    if not partial:
        for field in required_fields:
            if not data.get(field):
                return False, f"Missing required field: {field}"
    
    # Validate string lengths
    if data.get('title') and len(data['title']) > 255:
        return False, "Title too long (max 255 characters)"
    if data.get('company') and len(data['company']) > 255:
        return False, "Company name too long (max 255 characters)"
    if data.get('location') and len(data['location']) > 255:
        return False, "Location too long (max 255 characters)"
    if data.get('job_url') and len(data['job_url']) > 500:
        return False, "Job URL too long (max 500 characters)"
    
    # Validate application_status if provided
    valid_statuses = ['not_applied', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']
    if data.get('application_status') and data['application_status'] not in valid_statuses:
        return False, f"Invalid application_status. Must be one of: {', '.join(valid_statuses)}"
    
    return True, None


def validate_profile_data(data: dict) -> tuple:
    """Validate profile data fields. Returns (is_valid, error_message)"""
    if not data:
        return False, "No data provided"
    
    # Validate email format if provided
    if data.get('email'):
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, data['email']):
            return False, "Invalid email format"
    
    # Validate URL formats if provided
    url_fields = ['github_url', 'linkedin_url', 'resume_path']
    for field in url_fields:
        if data.get(field) and len(data[field]) > 500:
            return False, f"{field} too long (max 500 characters)"
    
    # Validate name length
    if data.get('name') and len(data['name']) > 255:
        return False, "Name too long (max 255 characters)"
    
    # Validate target_role length
    if data.get('target_role') and len(data['target_role']) > 255:
        return False, "Target role too long (max 255 characters)"
    
    return True, None


def _migrate_add_columns(engine):
    """Add new OPT-redesign columns to existing tables.

    SQLite supports ALTER TABLE ADD COLUMN for nullable/defaulted columns.
    Table names are derived from model __tablename__ to stay in sync.
    Idempotent — safe to run on every startup.
    """
    import sqlalchemy

    inspector = sqlalchemy.inspect(engine)

    migrations = [
        (Job.__tablename__, {
            'is_everify':          'BOOLEAN',
            'opt_field_related':   'BOOLEAN DEFAULT 0',
            'sponsorship_screen':  'BOOLEAN DEFAULT 0',
            'h1b_lca_count':       'INTEGER',
            'wage_level':          'INTEGER',
            'employer_match_conf': 'FLOAT',
            'freshness_hours':     'INTEGER',
            'opt_fit_score':       'INTEGER',
        }),
        (UserProfile.__tablename__, {
            'grad_date':         'DATE',
            'opt_start_date':    'DATE',
            'stem_eligible':     'BOOLEAN DEFAULT 1',
            'unemployment_days': 'INTEGER DEFAULT 0',
        }),
    ]

    with engine.connect() as conn:
        for table_name, new_columns in migrations:
            if not inspector.has_table(table_name):
                continue
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            for col_name, col_type in new_columns.items():
                if col_name not in existing:
                    conn.execute(sqlalchemy.text(
                        f'ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}'
                    ))
                    logger.info(f"Migration: added {col_name} to {table_name}")
        conn.commit()


app = Flask(__name__, 
            static_folder='../frontend/static',
            template_folder='../frontend/templates')

app.config.from_object(Config)
CORS(app)
db.init_app(app)

with app.app_context():
    db.create_all()
    _migrate_add_columns(db.engine)
    if not UserProfile.query.first():
        default_profile = UserProfile(
            name=Config.DEFAULT_NAME,
            github_url=Config.DEFAULT_GITHUB_URL,
            resume_path=Config.RESUME_PATH,
            target_role=Config.DEFAULT_TARGET_ROLE
        )
        db.session.add(default_profile)
        db.session.commit()
        logger.info("Created default user profile")


@app.route('/')
def index():
    return send_from_directory('../frontend/templates', 'index.html')


@app.route('/favicon.ico')
def favicon():
    return ('', 204)


@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    source = request.args.get('source')
    location = request.args.get('location')
    status = request.args.get('status')
    is_favorite = request.args.get('is_favorite')
    search = request.args.get('search')
    show_hidden = request.args.get('show_hidden', 'false')
    date_filter = request.args.get('date_filter')  # today, week, month
    
    query = Job.query
    
    if show_hidden != 'true':
        query = query.filter(Job.is_hidden == False)
    
    if source:
        query = query.filter(Job.source == source)
    
    if location:
        query = query.filter(Job.location.ilike(f'%{location}%'))
    
    if status:
        query = query.filter(Job.application_status == status)
    
    if is_favorite == 'true':
        query = query.filter(Job.is_favorite == True)
    
    if search:
        search_term = f'%{search}%'
        query = query.filter(
            db.or_(
                Job.title.ilike(search_term),
                Job.company.ilike(search_term),
                Job.description.ilike(search_term)
            )
        )
    
    # OPT-specific filters
    sponsorship_screen = request.args.get('sponsorship_screen')
    if sponsorship_screen == 'true':
        query = query.filter(Job.sponsorship_screen == True)
    elif sponsorship_screen == 'false':
        query = query.filter(db.or_(Job.sponsorship_screen == False, Job.sponsorship_screen == None))

    opt_field_related = request.args.get('opt_field_related')
    if opt_field_related == 'true':
        query = query.filter(Job.opt_field_related == True)

    min_opt_fit = request.args.get('min_opt_fit', type=int)
    if min_opt_fit is not None:
        query = query.filter(Job.opt_fit_score >= min_opt_fit)

    max_freshness = request.args.get('max_freshness', type=int)
    if max_freshness is not None:
        query = query.filter(Job.freshness_hours <= max_freshness)

    if date_filter:
        now = datetime.now(timezone.utc)
        if date_filter == 'today':
            start_date = now - timedelta(days=1)
        elif date_filter == 'week':
            start_date = now - timedelta(days=7)
        elif date_filter == 'month':
            start_date = now - timedelta(days=30)
        else:
            start_date = None
        
        if start_date:
            query = query.filter(
                db.or_(
                    Job.date_posted >= start_date,
                    db.and_(Job.date_posted == None, Job.date_scraped >= start_date)
                )
            )
    
    sort_by = request.args.get('sort_by', 'date')
    if sort_by == 'opt_fit_score':
        query = query.order_by(Job.opt_fit_score.desc().nullslast(), Job.date_posted.desc().nullslast())
    elif sort_by == 'match_score':
        query = query.order_by(Job.match_score.desc().nullslast(), Job.date_posted.desc().nullslast())
    elif sort_by == 'freshness':
        query = query.order_by(Job.freshness_hours.asc().nullslast(), Job.date_posted.desc().nullslast())
    else:
        query = query.order_by(Job.date_posted.desc().nullslast(), Job.date_scraped.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'jobs': [job.to_dict() for job in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    })


@app.route('/api/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id):
    job = db.get_or_404(Job, job_id, description=f"Job with id {job_id} not found")
    return jsonify(job.to_dict())


@app.route('/api/jobs/<int:job_id>', methods=['PUT'])
def update_job(job_id):
    job = db.get_or_404(Job, job_id, description=f"Job with id {job_id} not found")
    data = request.get_json()
    
    # Validate input (partial=True since we allow updating individual fields)
    is_valid, error_msg = validate_job_data(data, partial=True)
    if not is_valid:
        logger.warning(f"Job update validation failed: {error_msg}")
        return jsonify({'error': error_msg}), 400
    
    if 'is_favorite' in data:
        job.is_favorite = data['is_favorite']
    if 'is_hidden' in data:
        job.is_hidden = data['is_hidden']
    if 'application_status' in data:
        job.application_status = data['application_status']
        if data['application_status'] == 'applied' and not job.applied_date:
            job.applied_date = datetime.now(timezone.utc)
            job.is_applied = True
    if 'notes' in data:
        job.notes = data['notes']
    
    db.session.commit()
    return jsonify(job.to_dict())


@app.route('/api/jobs/<int:job_id>', methods=['DELETE'])
def delete_job(job_id):
    job = db.get_or_404(Job, job_id, description=f"Job with id {job_id} not found")
    hard = request.args.get('hard', 'false') == 'true'

    if hard:
        db.session.delete(job)
        db.session.commit()
        logger.info(f"Hard-deleted job {job_id}")
        return jsonify({'message': 'Job permanently deleted'})

    job.is_hidden = True
    db.session.commit()
    logger.info(f"Soft-hid job {job_id}")
    return jsonify({'message': 'Job hidden', 'job': job.to_dict()})


@app.route('/api/jobs/add', methods=['POST'])
def add_job():
    data = request.get_json()
    
    # Validate input
    is_valid, error_msg = validate_job_data(data, partial=False)
    if not is_valid:
        logger.warning(f"Job validation failed: {error_msg}")
        return jsonify({'error': error_msg}), 400
    
    job = Job(
        title=data.get('title'),
        company=data.get('company'),
        location=data.get('location'),
        description=data.get('description'),
        job_url=data.get('job_url'),
        source=data.get('source', 'manual'),
        job_type=data.get('job_type', 'internship'),
        date_posted=datetime.fromisoformat(data['date_posted']) if data.get('date_posted') else None
    )
    
    db.session.add(job)
    db.session.commit()
    return jsonify(job.to_dict()), 201


@app.route('/api/stats', methods=['GET'])
def get_stats():
    total_jobs = Job.query.filter(Job.is_hidden == False).count()
    applied_jobs = Job.query.filter(Job.is_applied == True, Job.is_hidden == False).count()
    favorite_jobs = Job.query.filter(Job.is_favorite == True, Job.is_hidden == False).count()
    response_rate = round((applied_jobs / total_jobs) * 100, 2) if total_jobs else 0
    
    today = datetime.now(timezone.utc) - timedelta(days=1)
    new_today = Job.query.filter(
        db.or_(
            Job.date_posted >= today,
            db.and_(Job.date_posted == None, Job.date_scraped >= today)
        ),
        Job.is_hidden == False
    ).count()
    
    by_source = db.session.query(
        Job.source, db.func.count(Job.id)
    ).filter(Job.is_hidden == False).group_by(Job.source).all()
    
    by_status = db.session.query(
        Job.application_status, db.func.count(Job.id)
    ).filter(Job.is_hidden == False).group_by(Job.application_status).all()
    
    by_location = db.session.query(
        Job.location, db.func.count(Job.id)
    ).filter(Job.is_hidden == False).group_by(Job.location).order_by(db.func.count(Job.id).desc()).limit(10).all()
    
    # Handle None values in location
    by_location_dict = {}
    for loc, count in by_location:
        by_location_dict[loc if loc else "Unknown"] = count
    
    return jsonify({
        'total_jobs': total_jobs,
        'applied_jobs': applied_jobs,
        'favorite_jobs': favorite_jobs,
        'response_rate': response_rate,
        'new_today': new_today,
        'by_source': dict(by_source),
        'by_status': dict(by_status),
        'by_location': by_location_dict
    })


@app.route('/api/profile', methods=['GET'])
def get_profile():
    profile = UserProfile.query.first()
    if profile:
        return jsonify(profile.to_dict())
    return jsonify({})


@app.route('/api/profile', methods=['PUT'])
def update_profile():
    profile = UserProfile.query.first()
    if not profile:
        profile = UserProfile()
        db.session.add(profile)
    
    data = request.get_json()
    
    # Validate input
    is_valid, error_msg = validate_profile_data(data)
    if not is_valid:
        logger.warning(f"Profile validation failed: {error_msg}")
        return jsonify({'error': error_msg}), 400
    
    if 'name' in data:
        profile.name = data['name']
    if 'email' in data:
        profile.email = data['email']
    if 'github_url' in data:
        profile.github_url = data['github_url']
    if 'linkedin_url' in data:
        profile.linkedin_url = data['linkedin_url']
    if 'resume_path' in data:
        profile.resume_path = data['resume_path']
    if 'target_role' in data:
        profile.target_role = data['target_role']

    # OPT timeline fields
    from datetime import date as date_type
    if 'grad_date' in data:
        profile.grad_date = (
            date_type.fromisoformat(data['grad_date']) if data['grad_date'] else None
        )
    if 'opt_start_date' in data:
        profile.opt_start_date = (
            date_type.fromisoformat(data['opt_start_date']) if data['opt_start_date'] else None
        )
    if 'stem_eligible' in data:
        profile.stem_eligible = bool(data['stem_eligible'])
    if 'unemployment_days' in data:
        profile.unemployment_days = int(data['unemployment_days'])
    
    db.session.commit()
    return jsonify(profile.to_dict())


@app.route('/api/search/logs', methods=['GET'])
def get_search_logs():
    logs = SearchLog.query.order_by(SearchLog.started_at.desc()).limit(50).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    data = request.get_json() or {}
    sources = data.get('sources') or ['linkedin', 'remoteok', 'themuse']
    keywords = data.get('keywords') or Config.SEARCH_KEYWORDS[:5]
    locations = data.get('locations') or Config.TARGET_LOCATIONS
    min_match_score = data.get('min_match_score', 40)

    try:
        from scrapers.job_scraper_manager import JobScraperManager
        manager = JobScraperManager(db.session, min_match_score=min_match_score)
        results = manager.scrape_all(sources=sources, keywords=keywords, locations=locations)
        return jsonify({
            'message': 'Scraping completed',
            'results': results
        })
    except Exception as e:
        logger.exception("Scrape failed")
        return jsonify({
            'message': 'Scraping failed',
            'error': str(e),
            'results': {'sources': {}, 'total_new_jobs': 0, 'total_matched_jobs': 0}
        }), 500


@app.route('/api/config/locations', methods=['GET'])
def get_locations():
    return jsonify(Config.TARGET_LOCATIONS)


@app.route('/api/config/keywords', methods=['GET'])
def get_keywords():
    return jsonify(Config.SEARCH_KEYWORDS)


@app.route('/api/runway', methods=['GET'])
def get_runway():
    """Compute OPT employment runway from the user profile dates."""
    from datetime import date as date_type

    profile = UserProfile.query.first()
    if not profile or not profile.opt_start_date:
        return jsonify({
            'error': 'Set opt_start_date in your profile first (PUT /api/profile).'
        }), 400

    today = date_type.today()
    opt_start = profile.opt_start_date
    stem = bool(profile.stem_eligible)
    unemployment_days = profile.unemployment_days or 0

    opt_end = opt_start + timedelta(days=365)
    stem_end = opt_end + timedelta(days=730) if stem else None
    effective_end = stem_end if stem else opt_end

    days_remaining = (effective_end - today).days
    days_elapsed = (today - opt_start).days

    unemployment_limit = 150 if stem else 90
    unemployment_remaining = max(0, unemployment_limit - unemployment_days)

    return jsonify({
        'opt_start_date': opt_start.isoformat(),
        'opt_end_date': opt_end.isoformat(),
        'stem_eligible': stem,
        'stem_end_date': stem_end.isoformat() if stem_end else None,
        'effective_end_date': effective_end.isoformat(),
        'days_remaining': days_remaining,
        'days_elapsed': days_elapsed,
        'unemployment_days_used': unemployment_days,
        'unemployment_limit': unemployment_limit,
        'unemployment_days_remaining': unemployment_remaining,
        'grad_date': profile.grad_date.isoformat() if profile.grad_date else None,
    })


@app.route('/api/sponsorship/refresh', methods=['POST'])
def refresh_sponsorship():
    """Re-run employer lookup + screen detection on all visible jobs.

    Call after loading new E-Verify / H-1B data to backfill OPT fields.
    """
    from scrapers.sponsorship_data import lookup_employer
    from scrapers.profile_matcher import ProfileMatcher

    pm = ProfileMatcher()
    jobs = Job.query.filter(Job.is_hidden == False).all()
    updated = 0

    for job in jobs:
        emp = lookup_employer(job.company or '', db.session)
        job.is_everify = emp['is_everify']
        job.h1b_lca_count = emp['h1b_lca_count']
        job.wage_level = emp['wage_level']
        job.employer_match_conf = emp['employer_match_conf']

        job.sponsorship_screen = pm.detect_sponsorship_screen(
            job.title, job.description,
        )
        job.opt_field_related = (job.match_score or 0) >= Config.OPT_FIELD_MATCH_MIN

        job.opt_fit_score = ProfileMatcher.compute_opt_fit_score(
            job.match_score, job.is_everify,
            job.sponsorship_screen, job.opt_field_related,
        )

        if job.date_posted:
            dp = job.date_posted
            if dp.tzinfo is None:
                dp = dp.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dp
            job.freshness_hours = max(0, int(delta.total_seconds() / 3600))

        updated += 1

    db.session.commit()
    return jsonify({'message': f'Refreshed {updated} jobs', 'updated': updated})


# NUWorks scraper instance (kept alive for Duo 2FA flow)
nuworks_scraper_instance = None

@app.route('/api/nuworks/login/start', methods=['POST'])
def nuworks_start_login():
    """Start NUWorks login - opens browser and enters credentials"""
    global nuworks_scraper_instance
    
    data = request.get_json() or {}
    username = data.get('username', Config.NUWORKS_USERNAME)
    password = data.get('password', Config.NUWORKS_PASSWORD)
    
    if not username or not password:
        return jsonify({
            'status': 'error',
            'message': 'Please provide your NUWorks username and password'
        }), 400
    
    from scrapers.nuworks_scraper import NUWorksScraper
    
    if nuworks_scraper_instance:
        nuworks_scraper_instance.close()
    
    nuworks_scraper_instance = NUWorksScraper(username=username, password=password, headless=False)
    result = nuworks_scraper_instance.start_login()
    
    return jsonify(result)


@app.route('/api/nuworks/login/check', methods=['GET'])
def nuworks_check_login():
    """Check if Duo 2FA is completed"""
    global nuworks_scraper_instance
    
    if not nuworks_scraper_instance:
        return jsonify({
            'status': 'error',
            'message': 'No active NUWorks session. Please start login first.'
        })
    
    result = nuworks_scraper_instance.check_login_status()
    return jsonify(result)


@app.route('/api/nuworks/scrape', methods=['POST'])
def nuworks_scrape():
    """Scrape NUWorks jobs after successful login"""
    global nuworks_scraper_instance
    
    if not nuworks_scraper_instance or not nuworks_scraper_instance.logged_in:
        return jsonify({
            'status': 'error',
            'message': 'Not logged into NUWorks. Please complete login first.'
        }), 400
    
    data = request.get_json() or {}
    keywords = data.get('keywords', Config.SEARCH_KEYWORDS[:5])
    locations = data.get('locations', Config.TARGET_LOCATIONS)
    
    total_jobs = 0
    new_jobs = 0

    for keyword in keywords:
        for location in locations:
            try:
                jobs = nuworks_scraper_instance.search_jobs(keyword, location)

                for job_data in jobs:
                    external_id = (job_data.get('external_id') or '').strip()
                    job_url = (job_data.get('job_url') or '').strip()

                    existing = None
                    if external_id:
                        existing = Job.query.filter_by(source='nuworks', external_id=external_id).first()
                    if not existing and job_url:
                        existing = Job.query.filter_by(source='nuworks', job_url=job_url).first()
                    if not existing:
                        existing = Job.query.filter_by(
                            source='nuworks',
                            title=job_data.get('title'),
                            company=job_data.get('company'),
                            location=job_data.get('location'),
                        ).first()

                    if not existing:
                        job = Job(
                            title=job_data.get('title'),
                            company=job_data.get('company'),
                            location=job_data.get('location'),
                            description=job_data.get('description'),
                            job_url=job_data.get('job_url'),
                            source='nuworks',
                            job_type=job_data.get('job_type', 'co-op'),
                            date_posted=job_data.get('date_posted'),
                            is_remote=job_data.get('is_remote', False),
                            external_id=external_id or None,
                        )
                        db.session.add(job)
                        new_jobs += 1

                    total_jobs += 1

            except Exception as e:
                logger.exception(f"Error scraping NUWorks {keyword} in {location}: {e}")
                continue

    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': f'Found {total_jobs} jobs, {new_jobs} new',
        'total_found': total_jobs,
        'new_jobs': new_jobs
    })


@app.route('/api/nuworks/close', methods=['POST'])
def nuworks_close():
    """Close NUWorks browser session"""
    global nuworks_scraper_instance
    
    if nuworks_scraper_instance:
        nuworks_scraper_instance.close()
        nuworks_scraper_instance = None
    
    return jsonify({'status': 'success', 'message': 'NUWorks session closed'})


if __name__ == '__main__':
    app.run(debug=True, port=Config.PORT)
