import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from backend.models import db, Job, SearchLog, UserProfile
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

app = Flask(__name__, 
            static_folder='../frontend/static',
            template_folder='../frontend/templates')

app.config.from_object(Config)
CORS(app)
db.init_app(app)

with app.app_context():
    db.create_all()
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
    db.session.delete(job)
    db.session.commit()
    logger.info(f"Deleted job {job_id}")
    return jsonify({'message': 'Job deleted successfully'})


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
    
    db.session.commit()
    return jsonify(profile.to_dict())


@app.route('/api/search/logs', methods=['GET'])
def get_search_logs():
    logs = SearchLog.query.order_by(SearchLog.started_at.desc()).limit(50).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    data = request.get_json() or {}
    sources = data.get('sources', ['linkedin', 'remoteok', 'themuse'])
    keywords = data.get('keywords', Config.SEARCH_KEYWORDS[:5])
    locations = data.get('locations') or Config.TARGET_LOCATIONS
    if not locations:
        locations = Config.TARGET_LOCATIONS
    min_match_score = data.get('min_match_score', 40)
    
    from scrapers.job_scraper_manager import JobScraperManager
    
    manager = JobScraperManager(db.session, min_match_score=min_match_score)
    results = manager.scrape_all(sources=sources, keywords=keywords, locations=locations)
    
    return jsonify({
        'message': 'Scraping completed',
        'results': results
    })


@app.route('/api/config/locations', methods=['GET'])
def get_locations():
    return jsonify(Config.TARGET_LOCATIONS)


@app.route('/api/config/keywords', methods=['GET'])
def get_keywords():
    return jsonify(Config.SEARCH_KEYWORDS)


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
                    existing = Job.query.filter_by(
                        source='nuworks',
                        title=job_data.get('title'),
                        company=job_data.get('company')
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
                            is_remote=job_data.get('is_remote', False)
                        )
                        db.session.add(job)
                        new_jobs += 1
                    
                    total_jobs += 1
                    
            except Exception as e:
                print(f"Error scraping NUWorks {keyword} in {location}: {e}")
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
    app.run(debug=True, port=5000)
