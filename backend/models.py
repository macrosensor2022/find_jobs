from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class Job(db.Model):
    __tablename__ = 'jobs'
    __table_args__ = (
        db.Index('idx_job_source', 'source'),
        db.Index('idx_job_status', 'application_status'),
        db.Index('idx_job_date_posted', 'date_posted'),
        db.Index('idx_job_is_hidden', 'is_hidden'),
        db.Index('idx_job_is_favorite', 'is_favorite'),
        db.Index('idx_job_is_applied', 'is_applied'),
        db.Index('idx_job_source_status', 'source', 'application_status'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255))
    description = db.Column(db.Text)
    job_url = db.Column(db.String(500))
    source = db.Column(db.String(50))  # linkedin, remoteok, themuse, etc.
    
    salary_min = db.Column(db.Integer)
    salary_max = db.Column(db.Integer)
    job_type = db.Column(db.String(50))  # full-time, internship, co-op
    
    date_posted = db.Column(db.DateTime)
    date_scraped = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    is_remote = db.Column(db.Boolean, default=False)
    is_favorite = db.Column(db.Boolean, default=False)
    is_applied = db.Column(db.Boolean, default=False)
    is_hidden = db.Column(db.Boolean, default=False)
    
    application_status = db.Column(db.String(50), default='not_applied')
    # Statuses: not_applied, applied, interviewing, offer, rejected, withdrawn
    
    notes = db.Column(db.Text)
    applied_date = db.Column(db.DateTime)
    
    external_id = db.Column(db.String(255))  # External job ID from source
    match_score = db.Column(db.Integer, default=0)  # Profile match score (0-100%)
    
    # OPT / sponsorship intelligence
    is_everify = db.Column(db.Boolean, nullable=True)
    opt_field_related = db.Column(db.Boolean, default=False)
    sponsorship_screen = db.Column(db.Boolean, default=False)
    h1b_lca_count = db.Column(db.Integer, nullable=True)
    wage_level = db.Column(db.Integer, nullable=True)
    employer_match_conf = db.Column(db.Float, nullable=True)
    freshness_hours = db.Column(db.Integer, nullable=True)
    opt_fit_score = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'company': self.company,
            'location': self.location,
            'description': self.description,
            'job_url': self.job_url,
            'source': self.source,
            'salary_min': self.salary_min,
            'salary_max': self.salary_max,
            'job_type': self.job_type,
            'date_posted': self.date_posted.isoformat() if self.date_posted else None,
            'date_scraped': self.date_scraped.isoformat() if self.date_scraped else None,
            'is_remote': self.is_remote,
            'is_favorite': self.is_favorite,
            'is_applied': self.is_applied,
            'is_hidden': self.is_hidden,
            'application_status': self.application_status,
            'notes': self.notes,
            'applied_date': self.applied_date.isoformat() if self.applied_date else None,
            'match_score': self.match_score,
            'is_everify': self.is_everify,
            'opt_field_related': self.opt_field_related,
            'sponsorship_screen': self.sponsorship_screen,
            'h1b_lca_count': self.h1b_lca_count,
            'wage_level': self.wage_level,
            'employer_match_conf': self.employer_match_conf,
            'freshness_hours': self.freshness_hours,
            'opt_fit_score': self.opt_fit_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Job {self.title} at {self.company}>'


class SearchLog(db.Model):
    __tablename__ = 'search_logs'
    __table_args__ = (
        db.Index('idx_searchlog_source', 'source'),
        db.Index('idx_searchlog_status', 'status'),
        db.Index('idx_searchlog_started', 'started_at'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50))
    keyword = db.Column(db.String(255))
    location = db.Column(db.String(255))
    jobs_found = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50))  # success, failed, in_progress
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)
    
    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'keyword': self.keyword,
            'location': self.location,
            'jobs_found': self.jobs_found,
            'status': self.status,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class UserProfile(db.Model):
    __tablename__ = 'user_profile'
    __table_args__ = (
        db.Index('idx_userprofile_email', 'email'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    github_url = db.Column(db.String(500))
    linkedin_url = db.Column(db.String(500))
    resume_path = db.Column(db.String(500))
    target_role = db.Column(db.String(255))
    
    # OPT timeline fields
    grad_date = db.Column(db.Date, nullable=True)
    opt_start_date = db.Column(db.Date, nullable=True)
    stem_eligible = db.Column(db.Boolean, default=True)
    unemployment_days = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'github_url': self.github_url,
            'linkedin_url': self.linkedin_url,
            'resume_path': self.resume_path,
            'target_role': self.target_role,
            'grad_date': self.grad_date.isoformat() if self.grad_date else None,
            'opt_start_date': self.opt_start_date.isoformat() if self.opt_start_date else None,
            'stem_eligible': self.stem_eligible,
            'unemployment_days': self.unemployment_days,
        }


class EVerifyEmployer(db.Model):
    __tablename__ = 'everify_employer'
    __table_args__ = (
        db.Index('idx_everify_normalized', 'normalized_name'),
        db.Index('idx_everify_state', 'state'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    employer_name = db.Column(db.String(500), nullable=False)
    normalized_name = db.Column(db.String(500), nullable=False)
    city = db.Column(db.String(255))
    state = db.Column(db.String(100))
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            'id': self.id,
            'employer_name': self.employer_name,
            'normalized_name': self.normalized_name,
            'city': self.city,
            'state': self.state,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }


class SponsorHistory(db.Model):
    __tablename__ = 'sponsor_history'
    __table_args__ = (
        db.Index('idx_sponsor_normalized', 'normalized_name'),
        db.Index('idx_sponsor_year', 'fiscal_year'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    employer_name = db.Column(db.String(500), nullable=False)
    normalized_name = db.Column(db.String(500), nullable=False)
    fiscal_year = db.Column(db.Integer)
    lca_count = db.Column(db.Integer)
    approvals = db.Column(db.Integer)
    denials = db.Column(db.Integer)
    median_wage = db.Column(db.Integer)
    prevailing_wage_level = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'id': self.id,
            'employer_name': self.employer_name,
            'normalized_name': self.normalized_name,
            'fiscal_year': self.fiscal_year,
            'lca_count': self.lca_count,
            'approvals': self.approvals,
            'denials': self.denials,
            'median_wage': self.median_wage,
            'prevailing_wage_level': self.prevailing_wage_level,
        }
