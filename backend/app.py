import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import date, datetime, timedelta, timezone
from backend.models import (
    db, Job, SearchLog, UserProfile, EVerifyEmployer, SponsorHistory,
    MetroOpportunity, MetroSocLca, UnparsedLocation,
    ProfileSkill, ProfileExperience, ProfileEducation, ProfileProject,
    Preference, WatchlistCompany, Application, ApplicationEvent,
    ApplicationPrep, Notification, SearchRun, SourceRun,
)
from config.settings import Config
import json
import logging
import threading
import copy

# Expected graduation from the candidate profile (MS CS, Northeastern).
_GRAD_DATE = date(2027, 5, 1)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Background scrape state (single-job queue)
_scrape_lock = threading.Lock()
_scrape_state = {
    'status': 'idle',  # idle | running | completed | failed
    'message': '',
    'started_at': None,
    'completed_at': None,
    'progress': {},
    'results': None,
    'error': None,
    'params': None,
}


def _run_scrape_job(sources, keywords, locations, min_match_score):
    """Run scrape in a background thread with its own app context."""
    with app.app_context():
        try:
            from scrapers.job_scraper_manager import JobScraperManager

            def on_progress(info):
                with _scrape_lock:
                    progress = dict(_scrape_state.get('progress') or {})
                    progress.update(info or {})
                    _scrape_state['progress'] = progress
                    if info and info.get('message'):
                        _scrape_state['message'] = info['message']
                    # Expose live totals while still running
                    if info and info.get('partial_results'):
                        _scrape_state['results'] = copy.deepcopy(info['partial_results'])

            manager = JobScraperManager(
                db.session,
                min_match_score=min_match_score,
                progress_callback=on_progress,
            )
            results = manager.scrape_all(
                sources=sources, keywords=keywords, locations=locations,
            )
            try:
                from services.batch_verify import verify_top_jobs
                results['verify'] = verify_top_jobs(
                    Job, session=db.session,
                    limit=int(getattr(Config, 'VERIFY_TOP_N', 15)),
                )
                # Don't dump per-job details into scrape status payload
                if isinstance(results.get('verify'), dict):
                    results['verify'] = {
                        k: results['verify'].get(k)
                        for k in ('checked', 'verified', 'dead', 'unreachable', 'unknown')
                    }
            except Exception:
                logger.exception('Post-scrape URL verification failed')

            with _scrape_lock:
                _scrape_state['status'] = 'completed'
                _scrape_state['results'] = results
                _scrape_state['completed_at'] = datetime.now(timezone.utc).isoformat()
                verify_bits = results.get('verify') or {}
                verified_n = verify_bits.get('verified', 0)
                _scrape_state['message'] = (
                    f"Done — {results.get('total_new_jobs', 0)} new jobs "
                    f"({results.get('total_matched_jobs', 0)} matched); "
                    f"{verified_n} apply links verified"
                )
                _scrape_state['progress'] = {
                    **(_scrape_state.get('progress') or {}),
                    'current_source': None,
                    'sources_done': list((results.get('sources') or {}).keys()),
                    'sources_total': len(sources),
                    'total_new_jobs': results.get('total_new_jobs', 0),
                    'total_matched_jobs': results.get('total_matched_jobs', 0),
                }
        except Exception as e:
            logger.exception('Background scrape failed')
            with _scrape_lock:
                _scrape_state['status'] = 'failed'
                _scrape_state['error'] = str(e)
                _scrape_state['completed_at'] = datetime.now(timezone.utc).isoformat()
                _scrape_state['message'] = f'Scrape failed: {e}'
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            try:
                db.session.remove()
            except Exception:
                pass


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
            'worksite_city':       'VARCHAR(255)',
            'worksite_state':      'VARCHAR(10)',
            'metro':               'VARCHAR(255)',
            'metro_code':          'VARCHAR(16)',
            'location_opportunity_score': 'FLOAT',
            'competition_score':   'FLOAT',
            'rank_score':          'FLOAT',
            'in_target_states':    'BOOLEAN',
            'required_years':      'FLOAT',
            'exp_hard_drop':       'BOOLEAN',
            'market':              'VARCHAR(8)',
            'salary_predicted':    'BOOLEAN',
            'description_partial': 'BOOLEAN',
            # Provenance
            'source_url':                 'VARCHAR(500)',
            'application_url':            'VARCHAR(500)',
            'application_url_status':     "VARCHAR(20) DEFAULT 'unknown'",
            'application_url_checked_at': 'DATETIME',
            'date_posted_origin':         'VARCHAR(20)',
            'last_verified_at':           'DATETIME',
            'verification_status':        "VARCHAR(20) DEFAULT 'unverified'",
            'is_expired':                 'BOOLEAN DEFAULT 0',
            # Dedup
            'dedupe_key':      'VARCHAR(255)',
            'duplicate_of_id': 'INTEGER',
            'alt_source_urls': 'TEXT',
            # Phase 12 — dedup/repost provenance
            'first_seen':         'DATETIME',
            'last_seen':          'DATETIME',
            'source_count':       'INTEGER DEFAULT 1',
            'source_list':        'TEXT',
            'possible_repost':    'BOOLEAN DEFAULT 0',
            # Work authorization
            'sponsorship_status':          "VARCHAR(10) DEFAULT 'unknown'",
            'sponsorship_evidence':        'TEXT',
            'sponsorship_evidence_source': 'VARCHAR(50)',
            'sponsorship_reason':          'VARCHAR(255)',
            # Role
            'role_family':     'VARCHAR(64)',
            'role_tier':       'INTEGER',
            'seniority_level': 'VARCHAR(24)',
            'remote_type':     'VARCHAR(12)',
            # Scores
            'candidate_match_score':  'INTEGER',
            'opportunity_score':      'INTEGER',
            'job_quality_score':      'INTEGER',
            'final_score':            'FLOAT',
            'match_breakdown':        'TEXT',
            'match_reasons':          'TEXT',
            'match_gaps':             'TEXT',
            'match_risks':            'TEXT',
            'opportunity_breakdown':  'TEXT',
            'quality_flags':          'TEXT',
            'freshness_bucket':       'VARCHAR(12)',
            'scored_at':              'DATETIME',
            'is_not_interested':      'BOOLEAN DEFAULT 0',
            'location_blocked':       'BOOLEAN DEFAULT 0',
            'role_blocked':           'BOOLEAN DEFAULT 0',
            # Phase 2 / 5 / 9 / 10
            'application_priority_score':  'INTEGER',
            'application_recommendation':  'VARCHAR(16)',
            'application_readiness_score': 'INTEGER',
            'application_effort_estimate': 'VARCHAR(16)',
            'competition_signal':          'VARCHAR(16)',
            'applicant_count':             'INTEGER',
            'applicant_count_source':      'VARCHAR(50)',
            'competition_captured_at':     'DATETIME',
            'competition_breakdown':       'TEXT',
            'readiness_breakdown':         'TEXT',
            'skill_gap_matrix':            'TEXT',
            'hidden_fit':                  'BOOLEAN DEFAULT 0',
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

    # Indexes declared on the model are only created with the table, so add
    # them explicitly for columns introduced by the ALTER TABLE pass above.
    late_indexes = [
        ('idx_job_final_score', Job.__tablename__, 'final_score'),
        ('idx_job_match', Job.__tablename__, 'candidate_match_score'),
        ('idx_job_dedupe_key', Job.__tablename__, 'dedupe_key'),
        ('idx_job_expired', Job.__tablename__, 'is_expired'),
        ('idx_job_company', Job.__tablename__, 'company'),
        ('idx_job_role_tier', Job.__tablename__, 'role_tier'),
        ('idx_job_sponsorship', Job.__tablename__, 'sponsorship_status'),
        ('idx_job_eligibility', Job.__tablename__,
         'location_blocked, role_blocked, is_expired'),
    ]
    with engine.connect() as conn:
        for index_name, table_name, column in late_indexes:
            try:
                conn.execute(sqlalchemy.text(
                    f'CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column})'
                ))
            except Exception as exc:
                logger.warning('Could not create %s: %s', index_name, exc)
        conn.commit()

    # Rows stored before the provenance columns existed still hold the real URL
    # captured from the source in job_url. Copy it across and label it
    # 'unverified' — obtained from the source but not yet checked. Nothing is
    # invented here and no URL is ever constructed from a pattern.
    backfills = [
        (f"UPDATE {Job.__tablename__} SET application_url = job_url "
         "WHERE (application_url IS NULL OR application_url = '') "
         "  AND job_url IS NOT NULL AND job_url != ''", 'application_url'),
        (f"UPDATE {Job.__tablename__} SET application_url_status = 'unverified' "
         "WHERE application_url IS NOT NULL AND application_url != '' "
         "  AND (application_url_status IS NULL OR application_url_status = 'unknown')",
         'application_url_status'),
    ]
    with engine.connect() as conn:
        for statement, label in backfills:
            try:
                result = conn.execute(sqlalchemy.text(statement))
                if result.rowcount:
                    logger.info('Backfilled %s for %s jobs', label, result.rowcount)
            except Exception as exc:
                logger.warning('Could not backfill %s: %s', label, exc)
        conn.commit()


def _seed_profile_data():
    """Seed profile skills, education, experience, watchlist and preferences once.

    Only inserts what is missing. User edits are never overwritten. Experience
    is taken from Config.EXPERIENCE (already documented in PROFILE_SUMMARY);
    no employers, dates, or projects are invented.
    """
    from datetime import date as _date

    seeded = []

    if ProfileSkill.query.count() == 0:
        for name, category, proficiency in Config.PROFILE_SKILLS:
            db.session.add(ProfileSkill(
                name=name, category=category, proficiency=proficiency,
            ))
        seeded.append(f'{len(Config.PROFILE_SKILLS)} skills')

    if ProfileEducation.query.count() == 0:
        for entry in Config.EDUCATION:
            end = None
            if entry.get('end_date'):
                end = _date.fromisoformat(entry['end_date'])
            db.session.add(ProfileEducation(
                degree=entry.get('degree'), field=entry.get('field'),
                school=entry.get('school'), gpa=entry.get('gpa'),
                end_date=end, is_current=entry.get('is_current', False),
            ))
        seeded.append(f'{len(Config.EDUCATION)} education records')

    if ProfileExperience.query.count() == 0:
        for entry in getattr(Config, 'EXPERIENCE', []):
            start = (
                _date.fromisoformat(entry['start_date'])
                if entry.get('start_date') else None
            )
            end = (
                _date.fromisoformat(entry['end_date'])
                if entry.get('end_date') else None
            )
            db.session.add(ProfileExperience(
                title=entry['title'],
                company=entry.get('company'),
                location=entry.get('location'),
                start_date=start,
                end_date=end,
                employment_type=entry.get('employment_type'),
                description=entry.get('description'),
                skills_used=json.dumps(entry.get('skills_used') or []),
            ))
        seeded.append(f'{len(Config.EXPERIENCE)} experience records')

    if WatchlistCompany.query.count() == 0:
        from services.dedupe import normalize_company
        for name in Config.WATCHLIST_COMPANIES:
            db.session.add(WatchlistCompany(
                name=name, normalized_name=normalize_company(name), priority=2,
            ))
        seeded.append(f'{len(Config.WATCHLIST_COMPANIES)} watchlist companies')

    defaults = {
        'location_preferences': {
            'preferred_states': Config.PREFERRED_STATES,
            'acceptable_states': Config.ACCEPTABLE_STATES,
            'excluded_states': Config.EXCLUDED_STATES,
            'allow_remote_us': Config.ALLOW_REMOTE_US,
            'allow_hybrid': Config.ALLOW_HYBRID,
            'allow_relocation': Config.ALLOW_RELOCATION,
        },
        'match_weights': Config.MATCH_WEIGHTS,
        'final_score_weights': {
            'candidate_match': Config.CANDIDATE_MATCH_WEIGHT,
            'opportunity': Config.OPPORTUNITY_WEIGHT,
        },
        'schedule': {
            'enabled': Config.SCHEDULE_ENABLED,
            'hour': Config.SCHEDULE_HOUR,
            'minute': Config.SCHEDULE_MINUTE,
            'timezone': Config.SCHEDULE_TIMEZONE,
            'sources': Config.DAILY_SOURCES,
        },
        'followup_days': Config.FOLLOWUP_DAYS,
    }
    for key, value in defaults.items():
        if not Preference.query.filter_by(key=key).first():
            db.session.add(Preference(key=key, value=json.dumps(value)))
            seeded.append(f'preference:{key}')

    if seeded:
        db.session.commit()
        logger.info('Seeded profile data: %s', ', '.join(seeded))


def _rescore_unscored_jobs(flask_app, limit=400):
    """Fill final_score on older rows so the Today view is not empty.

    Runs in a background thread so startup stays fast. Never invents jobs;
    it only re-scores listings already stored.
    """
    def _run():
        with flask_app.app_context():
            from services.dedupe import build_dedupe_key
            from services.freshness import is_expired as freshness_is_expired
            from services.ranking import apply_to_model, score_job

            jobs = (
                Job.query.filter(Job.final_score.is_(None))
                .order_by(Job.id.desc())
                .limit(limit)
                .all()
            )
            if not jobs:
                return
            logger.info('Rescoring %s jobs with no final_score', len(jobs))
            watchlist = [
                {'name': r.name, 'priority': r.priority}
                for r in WatchlistCompany.query.filter_by(is_active=True).all()
            ] or [{'name': n, 'priority': 2} for n in Config.WATCHLIST_COMPANIES]
            loc_prefs = None
            row = Preference.query.filter_by(key='location_preferences').first()
            if row and isinstance(row.parsed, dict):
                loc_prefs = row.parsed
            scored = 0
            for job in jobs:
                try:
                    job.is_expired = freshness_is_expired(job.date_posted)
                    job.dedupe_key = job.dedupe_key or build_dedupe_key(job)
                    result = score_job({
                        'title': job.title,
                        'company': job.company,
                        'location': job.location,
                        'description': job.description,
                        'source': job.source,
                        'date_posted': job.date_posted,
                        'is_remote': job.is_remote,
                        'worksite_state': job.worksite_state,
                        'application_url': job.application_url or job.job_url,
                        'application_url_status': job.application_url_status,
                        'verification_status': job.verification_status,
                        'is_expired': job.is_expired,
                        'duplicate_of_id': job.duplicate_of_id,
                    }, watchlist=watchlist, location_prefs=loc_prefs)
                    apply_to_model(job, result)
                    if result['match']['eligible'] and job.is_hidden and not job.is_applied:
                        job.is_hidden = False
                    elif not result['match']['eligible']:
                        job.is_hidden = True
                    scored += 1
                except Exception:
                    logger.exception('Rescore failed for job %s', job.id)
            db.session.commit()
            logger.info('Rescored %s previously un-scored jobs', scored)

    threading.Thread(target=_run, daemon=True, name='rescore-unscored').start()


app = Flask(__name__, 
            static_folder='../frontend/static',
            template_folder='../frontend/templates')

app.config.from_object(Config)
CORS(app)
db.init_app(app)

with app.app_context():
    from datetime import date as _date
    db.create_all()
    _migrate_add_columns(db.engine)
    profile = UserProfile.query.first()
    if not profile:
        profile = UserProfile(
            name=Config.DEFAULT_NAME,
            email=getattr(Config, 'DEFAULT_EMAIL', ''),
            github_url=Config.DEFAULT_GITHUB_URL,
            linkedin_url=getattr(Config, 'DEFAULT_LINKEDIN_URL', ''),
            resume_path=Config.RESUME_PATH,
            target_role=Config.DEFAULT_TARGET_ROLE,
            grad_date=_GRAD_DATE,
            stem_eligible=True,
        )
        db.session.add(profile)
        db.session.commit()
        logger.info("Created default user profile")
    else:
        # Fill blanks only. Edits made in the UI must survive a restart.
        profile.name = profile.name or Config.DEFAULT_NAME
        profile.email = profile.email or getattr(Config, 'DEFAULT_EMAIL', '')
        profile.github_url = profile.github_url or Config.DEFAULT_GITHUB_URL
        profile.linkedin_url = (
            profile.linkedin_url or getattr(Config, 'DEFAULT_LINKEDIN_URL', '')
        )
        profile.target_role = profile.target_role or Config.DEFAULT_TARGET_ROLE
        if not profile.grad_date:
            profile.grad_date = _GRAD_DATE
        if profile.stem_eligible is None:
            profile.stem_eligible = True
        db.session.commit()

    _seed_profile_data()

_rescore_unscored_jobs(app)

# The scheduler is started from run.py so the reloader cannot double-start it.


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

    # ---- Smart filters on the new scoring dimensions ----------------------
    min_match = request.args.get('min_match', type=int)
    if min_match is not None:
        query = query.filter(Job.candidate_match_score >= min_match)

    min_final = request.args.get('min_final', type=float)
    if min_final is not None:
        query = query.filter(Job.final_score >= min_final)

    min_priority = request.args.get('min_priority', type=int)
    if min_priority is not None:
        query = query.filter(Job.application_priority_score >= min_priority)

    recommendation = request.args.get('recommendation')
    if recommendation:
        allowed = [r.strip() for r in recommendation.split(',') if r.strip()]
        if allowed:
            query = query.filter(Job.application_recommendation.in_(allowed))

    readiness_min = request.args.get('min_readiness', type=int)
    if readiness_min is not None:
        query = query.filter(Job.application_readiness_score >= readiness_min)

    sponsorship_status = request.args.get('sponsorship_status')
    if sponsorship_status:
        allowed = [s.strip() for s in sponsorship_status.split(',') if s.strip()]
        if allowed:
            query = query.filter(Job.sponsorship_status.in_(allowed))

    role_tier = request.args.get('role_tier')
    if role_tier:
        tiers = [int(t) for t in role_tier.split(',') if t.strip().isdigit()]
        if tiers:
            query = query.filter(Job.role_tier.in_(tiers))

    remote_type = request.args.get('remote_type')
    if remote_type:
        types = [t.strip() for t in remote_type.split(',') if t.strip()]
        if types:
            query = query.filter(Job.remote_type.in_(types))

    freshness_bucket = request.args.get('freshness_bucket')
    if freshness_bucket:
        buckets = [b.strip() for b in freshness_bucket.split(',') if b.strip()]
        if buckets:
            query = query.filter(Job.freshness_bucket.in_(buckets))

    company = request.args.get('company')
    if company:
        query = query.filter(Job.company.ilike(f'%{company}%'))

    if request.args.get('has_salary') == 'true':
        query = query.filter(db.or_(Job.salary_min.isnot(None), Job.salary_max.isnot(None)))

    if request.args.get('apply_url_verified') == 'true':
        query = query.filter(Job.application_url_status == 'verified')

    if request.args.get('has_apply_url') == 'true':
        query = query.filter(Job.application_url.isnot(None))

    include_expired = request.args.get('include_expired', 'false')
    if include_expired != 'true':
        query = query.filter(db.or_(Job.is_expired.is_(False), Job.is_expired.is_(None)))

    if request.args.get('not_interested') == 'true':
        query = query.filter(Job.is_not_interested.is_(True))
    else:
        query = query.filter(
            db.or_(Job.is_not_interested.is_(False), Job.is_not_interested.is_(None))
        )

    if request.args.get('is_applied') == 'true':
        query = query.filter(Job.is_applied.is_(True))

    # "Only show jobs I should realistically apply to" — same definition the
    # daily briefing uses, so the two views can never disagree.
    if request.args.get('realistic_only') == 'true':
        from services.briefing import realistic_filters

        for condition in realistic_filters(Job):
            query = query.filter(condition)

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
            # Include either newly posted OR newly (re)discovered jobs so a
            # scrape today surfaces in Today/week filters even when the
            # original posting date is older.
            query = query.filter(
                db.or_(
                    Job.date_posted >= start_date,
                    Job.date_scraped >= start_date,
                )
            )
    
    sort_by = request.args.get('sort_by', 'final_score')
    if sort_by == 'final_score':
        query = query.order_by(
            Job.final_score.desc().nullslast(),
            Job.candidate_match_score.desc().nullslast(),
        )
    elif sort_by == 'candidate_match':
        query = query.order_by(
            Job.candidate_match_score.desc().nullslast(),
            Job.final_score.desc().nullslast(),
        )
    elif sort_by == 'opportunity':
        query = query.order_by(
            Job.opportunity_score.desc().nullslast(),
            Job.final_score.desc().nullslast(),
        )
    elif sort_by == 'quality':
        query = query.order_by(Job.job_quality_score.desc().nullslast())
    elif sort_by == 'rank_score':
        query = query.order_by(Job.rank_score.desc().nullslast(), Job.match_score.desc().nullslast())
    elif sort_by == 'priority':
        query = query.order_by(
            Job.application_priority_score.desc().nullslast(),
            Job.final_score.desc().nullslast(),
        )
    elif sort_by == 'location_opportunity':
        query = query.order_by(
            Job.location_opportunity_score.desc().nullslast(),
            Job.match_score.desc().nullslast(),
        )
    elif sort_by == 'opt_fit_score':
        query = query.order_by(Job.opt_fit_score.desc().nullslast(), Job.date_posted.desc().nullslast())
    elif sort_by == 'match_score':
        query = query.order_by(Job.match_score.desc().nullslast(), Job.date_posted.desc().nullslast())
    elif sort_by == 'freshness':
        query = query.order_by(Job.freshness_hours.asc().nullslast(), Job.date_posted.desc().nullslast())
    else:
        query = query.order_by(Job.date_posted.desc().nullslast(), Job.date_scraped.desc())
    
    # Optional TARGET_STATES-only view
    target_only = request.args.get('target_states_only')
    if target_only == 'true':
        query = query.filter(Job.in_target_states == True)

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
    if 'is_not_interested' in data:
        job.is_not_interested = bool(data['is_not_interested'])

    db.session.commit()
    return jsonify(job.to_dict())


# =============================================================================
# Daily briefing — "what should I apply to today?"
# =============================================================================

@app.route('/api/briefing', methods=['GET'])
def get_briefing():
    from services.briefing import build_briefing

    limit = request.args.get('limit', Config.DAILY_TOP_N, type=int)
    payload = build_briefing(
        {
            'Job': Job,
            'Application': Application,
            'SearchRun': SearchRun,
            'WatchlistCompany': WatchlistCompany,
            'Notification': Notification,
        },
        profile=UserProfile.query.first(),
        limit=max(1, min(limit, 50)),
        realistic=request.args.get('realistic', 'true').lower() != 'false',
    )
    return jsonify(payload)


@app.route('/api/sources/metrics', methods=['GET'])
def get_source_metrics():
    from services.briefing import source_metrics

    days = request.args.get('days', 30, type=int)
    return jsonify({
        'days': days,
        'sources': source_metrics({'SourceRun': SourceRun, 'Job': Job}, days=days),
    })


@app.route('/api/search-runs', methods=['GET'])
def get_search_runs():
    limit = request.args.get('limit', 25, type=int)
    runs = (
        SearchRun.query.order_by(SearchRun.started_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    out = []
    for run in runs:
        entry = run.to_dict()
        entry['source_runs'] = [
            row.to_dict() for row in
            SourceRun.query.filter_by(search_run_id=run.id).all()
        ]
        out.append(entry)
    return jsonify({'runs': out})


# =============================================================================
# Verification — we only check URLs we already hold
# =============================================================================

@app.route('/api/jobs/<int:job_id>/verify', methods=['POST'])
def verify_job(job_id):
    from services.verification import apply_verification, verify_url

    job = db.get_or_404(Job, job_id, description=f"Job with id {job_id} not found")
    url = job.application_url or job.job_url
    result = verify_url(url)
    apply_verification(job, result)
    db.session.commit()
    return jsonify({'job': job.to_dict(), 'verification': result})


@app.route('/api/jobs/verify-top', methods=['POST'])
def verify_top_jobs_endpoint():
    """Live-check application URLs for the current top ranked jobs.

    Never invents URLs — only verifies what is already stored.
    """
    data = request.get_json() or {}
    limit = int(data.get('limit') or getattr(Config, 'VERIFY_TOP_N', 15))
    from services.batch_verify import verify_top_jobs
    summary = verify_top_jobs(Job, session=db.session, limit=limit)
    return jsonify({
        'checked': summary.get('checked', 0),
        'verified': summary.get('verified', 0),
        'dead': summary.get('dead', 0),
        'unreachable': summary.get('unreachable', 0),
        'unknown': summary.get('unknown', 0),
        'details': summary.get('details', [])[:limit],
    })


# =============================================================================
# Application preparation — drafts only, never submits
# =============================================================================

@app.route('/api/jobs/<int:job_id>/prepare', methods=['POST', 'GET'])
def prepare_application(job_id):
    from services.application_prep import build_prep

    job = db.get_or_404(Job, job_id, description=f"Job with id {job_id} not found")
    profile = UserProfile.query.first()
    skills = [
        (s.name, s.category, s.proficiency)
        for s in ProfileSkill.query.filter_by(is_active=True).all()
    ] or Config.PROFILE_SKILLS

    prep = build_prep(
        job,
        profile=profile.to_dict() if profile else None,
        education=[e.to_dict() for e in ProfileEducation.query.all()],
        experiences=[e.to_dict() for e in ProfileExperience.query.all()],
        projects=[p.to_dict() for p in ProfileProject.query.all()],
        profile_skills=skills,
    )

    record = ApplicationPrep.query.filter_by(job_id=job.id).first()
    if not record:
        record = ApplicationPrep(job_id=job.id)
        db.session.add(record)
    record.resume_recommendation = prep['resume_recommendation']
    record.resume_bullets = json.dumps(prep['resume_bullets'])
    record.cover_letter = prep['cover_letter']
    record.professional_summary = prep['professional_summary']
    record.screening_questions = json.dumps(prep['screening_questions'])
    record.highlight_skills = json.dumps(prep['highlight_skills'])
    record.generated_at = datetime.now(timezone.utc)
    db.session.commit()

    prep['id'] = record.id
    return jsonify(prep)


# =============================================================================
# Application tracker — only the user marks a job as applied
# =============================================================================

def _log_application_event(application, event_type, from_status=None,
                           to_status=None, detail=None):
    db.session.add(ApplicationEvent(
        application_id=application.id, event_type=event_type,
        from_status=from_status, to_status=to_status, detail=detail,
    ))


def _schedule_followup(application):
    """Set the next follow-up date from the configured cadence."""
    if not application.date_applied:
        application.next_followup_date = None
        return
    schedule = _preference('followup_days', Config.FOLLOWUP_DAYS) or []
    index = application.followup_count or 0
    if index >= len(schedule):
        application.next_followup_date = None
        return
    application.next_followup_date = (
        application.date_applied + timedelta(days=int(schedule[index]))
    )


def _preference(key, fallback=None):
    row = Preference.query.filter_by(key=key).first()
    if row is None:
        return fallback
    value = row.parsed
    return fallback if value is None else value


@app.route('/api/applications', methods=['GET'])
def list_applications():
    status = request.args.get('status')
    query = Application.query
    if status:
        query = query.filter(Application.status.in_(
            [s.strip().upper() for s in status.split(',') if s.strip()]
        ))
    applications = query.order_by(Application.updated_at.desc()).all()
    out = []
    for application in applications:
        entry = application.to_dict()
        if application.job:
            entry['job'] = {
                'id': application.job.id,
                'title': application.job.title,
                'company': application.job.company,
                'location': application.job.location,
                'candidate_match_score': application.job.candidate_match_score,
                'sponsorship_status': application.job.sponsorship_status,
                'role_tier': application.job.role_tier,
            }
        out.append(entry)
    return jsonify({'applications': out, 'statuses': Application.STATUSES})


@app.route('/api/applications', methods=['POST'])
def create_application():
    data = request.get_json() or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'error': 'job_id is required'}), 400
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({'error': f'Job {job_id} not found'}), 404

    existing = Application.query.filter_by(job_id=job_id).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    status = (data.get('status') or 'NEW').upper()
    if status not in Application.STATUSES:
        return jsonify({'error': f'Invalid status: {status}'}), 400

    application = Application(
        job_id=job_id,
        company=job.company,
        role=job.title,
        application_url=job.application_url or job.job_url,
        status=status,
        notes=data.get('notes'),
        resume_version=data.get('resume_version'),
        recruiter_name=data.get('recruiter_name'),
        recruiter_email=data.get('recruiter_email'),
    )
    if status == 'APPLIED':
        application.date_applied = datetime.now(timezone.utc)
    db.session.add(application)
    db.session.flush()
    _log_application_event(application, 'created', to_status=status)
    if status == 'APPLIED':
        job.is_applied = True
        job.applied_date = application.date_applied
        job.application_status = 'applied'
        _schedule_followup(application)
    db.session.commit()
    return jsonify(application.to_dict()), 201


@app.route('/api/applications/<int:application_id>', methods=['PUT'])
def update_application(application_id):
    application = db.get_or_404(Application, application_id)
    data = request.get_json() or {}

    if 'status' in data:
        new_status = (data['status'] or '').upper()
        if new_status not in Application.STATUSES:
            return jsonify({'error': f'Invalid status: {new_status}'}), 400
        if new_status != application.status:
            previous = application.status
            application.status = new_status
            _log_application_event(
                application, 'status_change',
                from_status=previous, to_status=new_status,
            )
            if new_status == 'APPLIED' and not application.date_applied:
                application.date_applied = datetime.now(timezone.utc)
                application.followup_count = 0
                _schedule_followup(application)
                if application.job:
                    application.job.is_applied = True
                    application.job.applied_date = application.date_applied
                    application.job.application_status = 'applied'
            if new_status in ('REJECTED', 'WITHDRAWN', 'OFFER', 'EXPIRED'):
                application.next_followup_date = None
                application.outcome = new_status.lower()

    for field in ('resume_version', 'cover_letter', 'recruiter_name',
                  'recruiter_email', 'notes', 'application_url'):
        if field in data:
            setattr(application, field, data[field])

    if 'interview_date' in data and data['interview_date']:
        dates = application.to_dict()['interview_dates']
        dates.append(data['interview_date'])
        application.interview_dates = json.dumps(dates)
        _log_application_event(application, 'interview',
                               detail=data['interview_date'])

    db.session.commit()
    return jsonify(application.to_dict())


@app.route('/api/applications/<int:application_id>/followup', methods=['POST'])
def log_followup(application_id):
    application = db.get_or_404(Application, application_id)
    application.followup_count = (application.followup_count or 0) + 1
    _log_application_event(
        application, 'followup',
        detail=(request.get_json() or {}).get('note'),
    )
    _schedule_followup(application)
    db.session.commit()
    return jsonify(application.to_dict())


@app.route('/api/applications/<int:application_id>/events', methods=['GET'])
def application_events(application_id):
    db.get_or_404(Application, application_id)
    events = (
        ApplicationEvent.query.filter_by(application_id=application_id)
        .order_by(ApplicationEvent.occurred_at.desc()).all()
    )
    return jsonify({'events': [event.to_dict() for event in events]})


@app.route('/api/followups', methods=['GET'])
def get_followups():
    now = datetime.now(timezone.utc)
    due = (
        Application.query.filter(
            Application.next_followup_date.isnot(None),
            Application.next_followup_date <= now,
            Application.status.notin_(['REJECTED', 'WITHDRAWN', 'OFFER', 'EXPIRED']),
        )
        .order_by(Application.next_followup_date.asc()).all()
    )
    upcoming = (
        Application.query.filter(
            Application.next_followup_date > now,
            Application.status.notin_(['REJECTED', 'WITHDRAWN', 'OFFER', 'EXPIRED']),
        )
        .order_by(Application.next_followup_date.asc()).limit(20).all()
    )
    return jsonify({
        'due': [a.to_dict() for a in due],
        'upcoming': [a.to_dict() for a in upcoming],
    })


# =============================================================================
# Preferences, watchlist, notifications, analytics
# =============================================================================

@app.route('/api/preferences', methods=['GET'])
def get_preferences():
    return jsonify({row.key: row.parsed for row in Preference.query.all()})


@app.route('/api/preferences', methods=['PUT'])
def update_preferences():
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Expected a JSON object of preference keys'}), 400
    for key, value in data.items():
        row = Preference.query.filter_by(key=key).first()
        if row:
            row.value = json.dumps(value)
        else:
            db.session.add(Preference(key=key, value=json.dumps(value)))
    db.session.commit()
    return jsonify({row.key: row.parsed for row in Preference.query.all()})


@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    from sqlalchemy import func

    rows = WatchlistCompany.query.order_by(
        WatchlistCompany.priority.asc(), WatchlistCompany.name.asc()
    ).all()
    out = []
    for row in rows:
        entry = row.to_dict()
        pattern = f'%{row.name}%'
        jobs = Job.query.filter(Job.company.ilike(pattern))
        matching = jobs.filter(
            Job.is_hidden.is_(False),
            Job.candidate_match_score >= Config.STRONG_MATCH_MIN,
        )
        avg = db.session.query(
            func.avg(Job.candidate_match_score)
        ).filter(Job.company.ilike(pattern)).scalar()
        applications = Application.query.filter(
            Application.company.ilike(pattern)
        ).all()
        entry.update({
            'jobs_found': jobs.count(),
            'matching_jobs': matching.count(),
            'avg_match': round(avg, 1) if avg else None,
            'applications': len(applications),
            'interviews': sum(
                1 for a in applications
                if a.status in ('PHONE_SCREEN', 'INTERVIEW', 'TECHNICAL', 'FINAL', 'OFFER')
            ),
            'offers': sum(1 for a in applications if a.status == 'OFFER'),
            'sponsorship_signals': _company_sponsorship_signals(pattern),
        })
        out.append(entry)
    return jsonify({'companies': out})


def _company_sponsorship_signals(pattern):
    """Evidence-based only: what the postings themselves said."""
    from sqlalchemy import func

    rows = (
        db.session.query(Job.sponsorship_status, func.count(Job.id))
        .filter(Job.company.ilike(pattern))
        .group_by(Job.sponsorship_status).all()
    )
    counts = {status or 'unknown': count for status, count in rows}
    everify = Job.query.filter(
        Job.company.ilike(pattern), Job.is_everify.is_(True)
    ).first()
    return {
        'posting_statuses': counts,
        'e_verify_listed': bool(everify),
        'note': 'Derived from posting text and public E-Verify data only',
    }


@app.route('/api/watchlist', methods=['POST'])
def add_watchlist_company():
    from services.dedupe import normalize_company

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    normalized = normalize_company(name)
    existing = WatchlistCompany.query.filter_by(normalized_name=normalized).first()
    if existing:
        existing.is_active = True
        existing.priority = data.get('priority', existing.priority)
        db.session.commit()
        return jsonify(existing.to_dict())
    row = WatchlistCompany(
        name=name, normalized_name=normalized,
        priority=int(data.get('priority', 2)), notes=data.get('notes'),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(row.to_dict()), 201


@app.route('/api/watchlist/<int:company_id>', methods=['DELETE'])
def remove_watchlist_company(company_id):
    row = db.get_or_404(WatchlistCompany, company_id)
    row.is_active = False
    db.session.commit()
    return jsonify({'message': f'{row.name} removed from the watchlist'})


@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    unread_only = request.args.get('unread', 'false') == 'true'
    query = Notification.query
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    rows = query.order_by(Notification.created_at.desc()).limit(100).all()
    return jsonify({
        'notifications': [row.to_dict() for row in rows],
        'unread_count': Notification.query.filter(
            Notification.is_read.is_(False)
        ).count(),
    })


@app.route('/api/notifications/read', methods=['POST'])
def mark_notifications_read():
    data = request.get_json() or {}
    ids = data.get('ids')
    query = Notification.query.filter(Notification.is_read.is_(False))
    if ids:
        query = query.filter(Notification.id.in_(ids))
    for row in query.all():
        row.is_read = True
    db.session.commit()
    return jsonify({'message': 'Marked as read'})


@app.route('/api/notifications/generate', methods=['POST'])
def generate_notifications_endpoint():
    from services.notifications import generate_notifications

    created = generate_notifications(db, Job, Application, Notification,
                                     WatchlistCompany)
    return jsonify({'created': created})


@app.route('/api/analytics/outcomes', methods=['GET'])
def analytics_outcomes():
    from services.analytics import build_analytics

    return jsonify(build_analytics(db, Job, Application))


@app.route('/api/analytics/employer-radar', methods=['GET'])
def analytics_employer_radar():
    """Which employers are actively hiring in the target lane right now."""
    from services.analytics import employer_radar

    days = request.args.get('days', default=30, type=int)
    limit = request.args.get('limit', default=12, type=int)
    return jsonify(employer_radar(db, Job, days=days, limit=limit))


@app.route('/api/analytics/market-skills', methods=['GET'])
def analytics_market_skills():
    """The skills the current scored pool asks for most (Phase 17)."""
    from services.analytics import _skill_demand

    limit = request.args.get('limit', default=15, type=int)
    # _skill_demand returns a sorted list of {skill, jobs, share}.
    demand = _skill_demand(db, Job, limit=limit)
    return jsonify({'skills': demand, 'note': 'From live scored full-time jobs.'})


@app.route('/api/search/health', methods=['GET'])
def search_health_endpoint():
    """Phase 20 — diagnostics for the search pipeline."""
    from services.analytics import search_health
    from backend.models import SearchRun

    return jsonify(search_health(db, Job, SearchRun))


@app.route('/api/jobs/<int:job_id>/why-hidden', methods=['GET'])
def job_why_hidden(job_id):
    """Phase 15 — why a job is not in the realistic apply list."""
    from services.briefing import why_hidden

    job = db.session.get(Job, job_id)
    if job is None:
        return jsonify({'job_id': job_id, 'reasons': []})
    return jsonify({'job_id': job_id, 'reasons': why_hidden(job)})


@app.route('/api/external-search', methods=['GET'])
def external_search_links():
    """Launcher for sites that cannot be integrated programmatically."""
    query = request.args.get('q') or (Config.SEARCH_KEYWORDS or ['Data Engineer'])[0]
    location = request.args.get('location') or 'United States'
    from urllib.parse import quote_plus

    links = [
        {
            'name': site['name'],
            'url': site['url'].format(q=quote_plus(query), loc=quote_plus(location)),
            'kind': 'External Search',
        }
        for site in Config.EXTERNAL_SEARCH_SITES
    ]
    return jsonify({
        'query': query,
        'location': location,
        'links': links,
        'note': 'These open the real websites. They are not integrated sources.',
    })


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


def _profile_payload(profile):
    """Contact fields plus structured education, skills, experience, prefs.

    Missing sections are empty lists, never fabricated records.
    """
    payload = profile.to_dict() if profile else {}
    payload.update({
        'education': [row.to_dict() for row in ProfileEducation.query.all()],
        'skills': [row.to_dict() for row in ProfileSkill.query.order_by(ProfileSkill.name).all()],
        'experience': [row.to_dict() for row in ProfileExperience.query.all()],
        'projects': [row.to_dict() for row in ProfileProject.query.all()],
        'preferences': {row.key: row.parsed for row in Preference.query.all()},
    })
    return payload


@app.route('/api/profile', methods=['GET'])
def get_profile():
    profile = UserProfile.query.first()
    if profile:
        return jsonify(_profile_payload(profile))
    return jsonify(_profile_payload(None))


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
    return jsonify(_profile_payload(profile))


@app.route('/api/search/logs', methods=['GET'])
def get_search_logs():
    logs = SearchLog.query.order_by(SearchLog.started_at.desc()).limit(50).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/api/metros/opportunity', methods=['GET'])
def metros_opportunity():
    """Location opportunity breakdown for verification metros.

    Query: ?metros=Hartford,Dallas-Fort Worth,Boston
    """
    from scrapers.metro_opportunity import get_metro_breakdown, compute_metro_opportunity_scores
    names = request.args.get('metros', 'Hartford,Dallas-Fort Worth,Boston')
    name_list = [n.strip() for n in names.split(',') if n.strip()]
    rebuild = request.args.get('rebuild') == 'true'
    try:
        if rebuild:
            compute_metro_opportunity_scores(db.session)
        rows = get_metro_breakdown(db.session, name_list)
        return jsonify({
            'metros': rows,
            'formula': (
                'opportunity = 0.25*normalize(DE_filings/metro_size) '
                '+ 0.45*(100-normalize(log DE_filings)) '
                '+ 0.30*(100*(1-top5_employer_share))  '
                '# density presence + inverse volume + inverse concentration'
            ),
            'socs': getattr(Config, 'DE_SOC_CODES', ['15-1243', '15-2051', '15-1211']),
            'target_states': getattr(Config, 'TARGET_STATES', []),
        })
    except AssertionError as e:
        return jsonify({'error': str(e), 'metros': []}), 409
    except Exception as e:
        logger.exception('metro opportunity failed')
        return jsonify({'error': str(e), 'metros': []}), 500


@app.route('/api/locations/unparsed', methods=['GET'])
def unparsed_locations():
    from scrapers.location_utils import unparsed_stats
    rows = UnparsedLocation.query.order_by(UnparsedLocation.hit_count.desc()).limit(50).all()
    return jsonify({
        'persisted': [{'location': r.location, 'count': r.hit_count} for r in rows],
        'memory': unparsed_stats(),
    })


@app.route('/api/config/states', methods=['GET'])
def get_target_states():
    prefs = {}
    row = Preference.query.filter_by(key='location_preferences').first()
    if row and isinstance(row.parsed, dict):
        prefs = row.parsed
    return jsonify({
        'target_states': prefs.get('preferred_states') or getattr(Config, 'PREFERRED_STATES', []),
        'preferred_states': prefs.get('preferred_states') or getattr(Config, 'PREFERRED_STATES', []),
        'acceptable_states': prefs.get('acceptable_states') or getattr(Config, 'ACCEPTABLE_STATES', []),
        'excluded_states': prefs.get('excluded_states') or getattr(Config, 'EXCLUDED_STATES', []),
        'allow_remote_us': prefs.get('allow_remote_us', getattr(Config, 'ALLOW_REMOTE_US', True)),
        'allow_hybrid': prefs.get('allow_hybrid', getattr(Config, 'ALLOW_HYBRID', True)),
        'allow_relocation': prefs.get('allow_relocation', getattr(Config, 'ALLOW_RELOCATION', True)),
        'linkedin_locations': getattr(Config, 'LINKEDIN_LOCATIONS', []),
        'editable': True,
    })


@app.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    """Start a scrape. Default is async (returns immediately); set sync=true for tests."""
    data = request.get_json() or {}
    sources = data.get('sources') or [
        'github_newgrad',
        'adzuna', 'jsearch', 'ats', 'remoteok', 'themuse', 'arbeitnow', 'remotive',
    ]
    # Full-time new-grad keywords only (no intern/co-op set)
    keywords = data.get('keywords') or list(Config.SEARCH_KEYWORDS[:12])
    locations = data.get('locations') or Config.TARGET_LOCATIONS
    min_match_score = data.get('min_match_score', 25)
    run_sync = bool(data.get('sync'))

    if run_sync:
        try:
            from scrapers.job_scraper_manager import JobScraperManager
            manager = JobScraperManager(db.session, min_match_score=min_match_score)
            results = manager.scrape_all(
                sources=sources, keywords=keywords, locations=locations,
            )
            return jsonify({
                'message': 'Scraping completed',
                'status': 'completed',
                'results': results,
            })
        except Exception as e:
            logger.exception("Scrape failed")
            return jsonify({
                'message': 'Scraping failed',
                'status': 'failed',
                'error': str(e),
                'results': {'sources': {}, 'total_new_jobs': 0, 'total_matched_jobs': 0},
            }), 500

    with _scrape_lock:
        if _scrape_state['status'] == 'running':
            return jsonify({
                'message': 'A scrape is already running',
                'status': 'running',
                'progress': dict(_scrape_state.get('progress') or {}),
            }), 409

        _scrape_state.update({
            'status': 'running',
            'message': 'Starting scrape…',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'completed_at': None,
            'progress': {
                'current_source': None,
                'sources_done': [],
                'sources_total': len(sources),
                'total_new_jobs': 0,
                'total_matched_jobs': 0,
            },
            'results': None,
            'error': None,
            'params': {
                'sources': sources,
                'keywords': keywords,
                'locations': locations,
                'min_match_score': min_match_score,
            },
        })

    thread = threading.Thread(
        target=_run_scrape_job,
        args=(sources, keywords, locations, min_match_score),
        daemon=True,
        name='job-scrape',
    )
    thread.start()

    return jsonify({
        'message': 'Scraping started',
        'status': 'running',
        'sources': sources,
    }), 202


@app.route('/api/scrape/status', methods=['GET'])
def scrape_status():
    """Poll background scrape progress."""
    with _scrape_lock:
        payload = {
            'status': _scrape_state['status'],
            'message': _scrape_state['message'],
            'started_at': _scrape_state['started_at'],
            'completed_at': _scrape_state['completed_at'],
            'progress': dict(_scrape_state.get('progress') or {}),
            'error': _scrape_state.get('error'),
            'results': _scrape_state.get('results'),
        }
    return jsonify(payload)


@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    from backend import scheduler as scheduler_module

    row = Preference.query.filter_by(key='schedule').first()
    settings = row.parsed if row else None
    return jsonify({
        'settings': settings or {
            'enabled': Config.SCHEDULE_ENABLED,
            'hour': Config.SCHEDULE_HOUR,
            'minute': Config.SCHEDULE_MINUTE,
            'timezone': Config.SCHEDULE_TIMEZONE,
            'sources': Config.DAILY_SOURCES,
        },
        'next_run': scheduler_module.next_run_time(),
    })


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
    Uses batch_lookup_employers for O(unique_companies) fuzzy work
    instead of O(jobs) scans.
    """
    from scrapers.sponsorship_data import batch_lookup_employers
    from scrapers.profile_matcher import ProfileMatcher

    pm = ProfileMatcher()
    jobs = Job.query.filter(Job.is_hidden == False).all()

    company_names = list({job.company or '' for job in jobs})
    emp_map = batch_lookup_employers(company_names, db.session)

    updated = 0
    for job in jobs:
        emp = emp_map.get(job.company or '', {})
        job.is_everify = emp.get('is_everify')
        job.h1b_lca_count = emp.get('h1b_lca_count')
        job.wage_level = emp.get('wage_level')
        job.employer_match_conf = emp.get('employer_match_conf')

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


# =============================================================================
# NUWorks — disabled from the normal workflow.
# The code below stays isolated behind NUWORKS_ENABLED so it can be revived
# later, but it never runs during scheduled or manual scrapes by default.
# =============================================================================

nuworks_scraper_instance = None


def _nuworks_guard():
    if not getattr(Config, 'NUWORKS_ENABLED', False):
        return jsonify({
            'status': 'disabled',
            'message': (
                'NUWorks is disabled. Set NUWORKS_ENABLED=true in your '
                'environment to re-enable it.'
            ),
        }), 403
    return None


@app.route('/api/nuworks/login/start', methods=['POST'])
def nuworks_start_login():
    """Start NUWorks login - opens browser and enters credentials"""
    global nuworks_scraper_instance

    blocked = _nuworks_guard()
    if blocked:
        return blocked

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

    blocked = _nuworks_guard()
    if blocked:
        return blocked

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

    blocked = _nuworks_guard()
    if blocked:
        return blocked

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
