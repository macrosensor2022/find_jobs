import json
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


def _load_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


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
        db.Index('idx_job_final_score', 'final_score'),
        db.Index('idx_job_match', 'candidate_match_score'),
        db.Index('idx_job_dedupe_key', 'dedupe_key'),
        db.Index('idx_job_expired', 'is_expired'),
        db.Index('idx_job_company', 'company'),
        db.Index('idx_job_role_tier', 'role_tier'),
        db.Index('idx_job_sponsorship', 'sponsorship_status'),
        db.Index('idx_job_daily', 'is_expired', 'is_hidden', 'final_score'),
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

    # Location / metro opportunity
    worksite_city = db.Column(db.String(255), nullable=True)
    worksite_state = db.Column(db.String(10), nullable=True)
    metro = db.Column(db.String(255), nullable=True)
    metro_code = db.Column(db.String(16), nullable=True)
    location_opportunity_score = db.Column(db.Float, nullable=True)
    competition_score = db.Column(db.Float, nullable=True)
    rank_score = db.Column(db.Float, nullable=True)
    in_target_states = db.Column(db.Boolean, nullable=True)
    required_years = db.Column(db.Float, nullable=True)
    exp_hard_drop = db.Column(db.Boolean, nullable=True)
    # Cheap SQL-filterable eligibility flags derived from the scoring engine.
    location_blocked = db.Column(db.Boolean, default=False)
    role_blocked = db.Column(db.Boolean, default=False)
    market = db.Column(db.String(8), nullable=True)  # US | IN
    salary_predicted = db.Column(db.Boolean, nullable=True)
    description_partial = db.Column(db.Boolean, nullable=True)

    # ---- Provenance: every claim must be traceable or explicitly unknown ----
    source_url = db.Column(db.String(500), nullable=True)      # listing page
    application_url = db.Column(db.String(500), nullable=True)  # real apply page
    application_url_status = db.Column(db.String(20), default='unknown')
    # unknown | unverified | verified | dead | search_fallback
    application_url_checked_at = db.Column(db.DateTime, nullable=True)
    date_posted_origin = db.Column(db.String(20), nullable=True)
    # feed | parsed_relative | unknown  — never fabricate a posting date
    last_verified_at = db.Column(db.DateTime, nullable=True)
    verification_status = db.Column(db.String(20), default='unverified')
    # unverified | active | expired | unreachable
    is_expired = db.Column(db.Boolean, default=False)

    # ---- Deduplication ------------------------------------------------------
    dedupe_key = db.Column(db.String(255), nullable=True)
    duplicate_of_id = db.Column(db.Integer, nullable=True)
    alt_source_urls = db.Column(db.Text, nullable=True)  # JSON list
    # ---- Phase 12 — dedup / repost provenance -------------------------------
    first_seen = db.Column(db.DateTime, nullable=True)     # first discovery
    last_seen = db.Column(db.DateTime, nullable=True)       # most recent rediscovery
    source_count = db.Column(db.Integer, default=1)         # distinct sources seen
    source_list = db.Column(db.Text, nullable=True)         # JSON list of source names
    possible_repost = db.Column(db.Boolean, default=False)  # posting date advanced on merge

    # ---- Work authorization (evidence-backed, never inferred from employer) --
    sponsorship_status = db.Column(db.String(10), default='unknown')  # green|yellow|red|unknown
    sponsorship_evidence = db.Column(db.Text, nullable=True)
    sponsorship_evidence_source = db.Column(db.String(50), nullable=True)
    sponsorship_reason = db.Column(db.String(255), nullable=True)

    # ---- Role classification ------------------------------------------------
    role_family = db.Column(db.String(64), nullable=True)
    role_tier = db.Column(db.Integer, nullable=True)   # 1 | 2 | 3 | None
    seniority_level = db.Column(db.String(24), nullable=True)
    remote_type = db.Column(db.String(12), nullable=True)  # remote|hybrid|onsite|unknown

    # ---- V3 — Industry intelligence -----------------------------------------
    industry = db.Column(db.String(64), nullable=True)
    industry_label = db.Column(db.String(128), nullable=True)
    under_the_radar = db.Column(db.Boolean, default=False)
    industry_opportunity = db.Column(db.String(16), nullable=True)  # HIGH|MEDIUM|LOW|UNKNOWN
    industry_opportunity_score = db.Column(db.Float, nullable=True)
    industry_evidence = db.Column(db.Text, nullable=True)  # JSON list of evidence strings
    # ---- V3 — Golden opportunity (sibling to final_score, never overriding) ---
    golden_opportunity_score = db.Column(db.Float, nullable=True)
    # ---- V3 — Contact intelligence (best recommended contact snapshot) ------
    recommended_contact_json = db.Column(db.Text, nullable=True)  # JSON dict

    # ---- Completion (all explainable; breakdown stored as JSON) -------------
    candidate_match_score = db.Column(db.Integer, nullable=True)
    opportunity_score = db.Column(db.Integer, nullable=True)
    job_quality_score = db.Column(db.Integer, nullable=True)
    final_score = db.Column(db.Float, nullable=True)
    match_breakdown = db.Column(db.Text, nullable=True)   # JSON dimension->score
    match_reasons = db.Column(db.Text, nullable=True)     # JSON list of "why apply"
    match_gaps = db.Column(db.Text, nullable=True)        # JSON list of gaps
    match_risks = db.Column(db.Text, nullable=True)       # JSON list of risks
    opportunity_breakdown = db.Column(db.Text, nullable=True)
    quality_flags = db.Column(db.Text, nullable=True)
    freshness_bucket = db.Column(db.String(12), nullable=True)
    scored_at = db.Column(db.DateTime, nullable=True)

    # ---- Phase 2 / 5 / 9 / 10 — priority, competition, readiness, effort -----
    application_priority_score = db.Column(db.Integer, nullable=True)
    application_recommendation = db.Column(db.String(16), nullable=True)  # apply_now|apply|watch|skip
    application_readiness_score = db.Column(db.Integer, nullable=True)
    application_effort_estimate = db.Column(db.String(16), nullable=True)  # band string
    competition_signal = db.Column(db.String(16), nullable=True)   # LOW|MODERATE|HIGH|VERY_HIGH|UNKNOWN
    applicant_count = db.Column(db.Integer, nullable=True)
    applicant_count_source = db.Column(db.String(50), nullable=True)
    competition_captured_at = db.Column(db.DateTime, nullable=True)
    competition_breakdown = db.Column(db.Text, nullable=True)  # JSON
    readiness_breakdown = db.Column(db.Text, nullable=True)    # JSON
    skill_gap_matrix = db.Column(db.Text, nullable=True)       # JSON matrix
    hidden_fit = db.Column(db.Boolean, default=False)

    is_not_interested = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    @property
    def apply_url(self):
        """The URL to send the user to, only when we actually have one."""
        return self.application_url or None

    def to_dict(self):
        data = {
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
            'worksite_city': self.worksite_city,
            'worksite_state': self.worksite_state,
            'metro': self.metro,
            'metro_code': self.metro_code,
            'location_opportunity_score': self.location_opportunity_score,
            'competition_score': self.competition_score,
            'rank_score': self.rank_score,
            'in_target_states': self.in_target_states,
            'required_years': self.required_years,
            'exp_hard_drop': self.exp_hard_drop,
            'location_blocked': bool(self.location_blocked),
            'role_blocked': bool(self.role_blocked),
            'market': self.market,
            'salary_predicted': self.salary_predicted,
            'description_partial': self.description_partial,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        data.update({
            'source_url': self.source_url,
            'application_url': self.application_url,
            'application_url_status': self.application_url_status or 'unknown',
            'application_url_checked_at': (
                self.application_url_checked_at.isoformat()
                if self.application_url_checked_at else None
            ),
            # Apply Now is shown only after the stored URL has been checked live.
            'can_apply': bool(
                self.application_url
                and self.application_url_status == 'verified'
            ),
            'can_apply_label': (
                'Apply now' if (
                    self.application_url
                    and self.application_url_status == 'verified'
                ) else (
                    'Unable to verify' if self.application_url else 'No apply link'
                )
            ),
            'date_posted_origin': self.date_posted_origin or 'unknown',
            'discovered_at': self.date_scraped.isoformat() if self.date_scraped else None,
            'last_verified_at': self.last_verified_at.isoformat() if self.last_verified_at else None,
            'verification_status': self.verification_status or 'unverified',
            'is_expired': bool(self.is_expired),
            'dedupe_key': self.dedupe_key,
            'duplicate_of_id': self.duplicate_of_id,
            'alt_source_urls': _load_json(self.alt_source_urls, []),
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'source_count': self.source_count or 1,
            'source_list': _load_json(self.source_list, []),
            'possible_repost': bool(self.possible_repost),
            'sponsorship_status': self.sponsorship_status or 'unknown',
            'sponsorship_evidence': self.sponsorship_evidence,
            'sponsorship_evidence_source': self.sponsorship_evidence_source,
            'sponsorship_reason': self.sponsorship_reason,
            'role_family': self.role_family,
            'role_tier': self.role_tier,
            'seniority_level': self.seniority_level,
            'remote_type': self.remote_type or 'unknown',
            'candidate_match_score': self.candidate_match_score,
            'opportunity_score': self.opportunity_score,
            'job_quality_score': self.job_quality_score,
            'final_score': self.final_score,
            'match_breakdown': _load_json(self.match_breakdown, {}),
            'match_reasons': _load_json(self.match_reasons, []),
            'match_gaps': _load_json(self.match_gaps, []),
            'match_risks': _load_json(self.match_risks, []),
            'opportunity_breakdown': _load_json(self.opportunity_breakdown, {}),
            'quality_flags': _load_json(self.quality_flags, []),
            'freshness_bucket': self.freshness_bucket,
            'scored_at': self.scored_at.isoformat() if self.scored_at else None,
            'is_not_interested': bool(self.is_not_interested),
            'salary_display': self._salary_display(),
            # Phase 2 / 5 / 9 / 10
            'application_priority_score': self.application_priority_score,
            'application_recommendation': self.application_recommendation,
            'application_readiness_score': self.application_readiness_score,
            'application_effort_estimate': self.application_effort_estimate,
            'competition_signal': self.competition_signal,
            'applicant_count': self.applicant_count,
            'applicant_count_source': self.applicant_count_source,
            'competition_captured_at': (
                self.competition_captured_at.isoformat()
                if self.competition_captured_at else None
            ),
            'competition_breakdown': _load_json(self.competition_breakdown, {}),
            'readiness_breakdown': _load_json(self.readiness_breakdown, {}),
            'skill_gap_matrix': _load_json(self.skill_gap_matrix, []),
            'hidden_fit': bool(self.hidden_fit),
            'recommendation': (
                self.application_recommendation or 'watch'
            ),
            'application_readiness': self.application_readiness_score,
            # V3 — Industry intelligence
            'industry': self.industry,
            'industry_label': self.industry_label,
            'under_the_radar': bool(self.under_the_radar),
            'industry_opportunity': self.industry_opportunity or 'UNKNOWN',
            'industry_opportunity_score': self.industry_opportunity_score,
            'industry_evidence': _load_json(self.industry_evidence, []),
            # V3 — Golden opportunity
            'golden_opportunity_score': self.golden_opportunity_score,
            # V3 — Contact intelligence
            'recommended_contact': _load_json(self.recommended_contact_json, None),
        })
        return data

    def _salary_display(self):
        """Never invent a salary. Predicted values are labelled as such."""
        if not self.salary_min and not self.salary_max:
            return 'Unknown'
        if self.salary_min and self.salary_max:
            base = f'${self.salary_min:,} - ${self.salary_max:,}'
        else:
            base = f'${(self.salary_min or self.salary_max):,}'
        if self.salary_predicted:
            return f'{base} (estimated by source)'
        return base

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


class MetroSocLca(db.Model):
    """Aggregate DOL LCA filings by CBSA metro × SOC × fiscal year."""
    __tablename__ = 'metro_soc_lca'
    __table_args__ = (
        db.Index('idx_metro_soc_year', 'metro_code', 'soc_code', 'fiscal_year'),
        db.Index('idx_metro_soc_metro', 'metro_code'),
    )

    id = db.Column(db.Integer, primary_key=True)
    metro_code = db.Column(db.String(16), nullable=False)
    metro_name = db.Column(db.String(255), nullable=False)
    soc_code = db.Column(db.String(16), nullable=False)
    fiscal_year = db.Column(db.Integer, nullable=False)
    filing_count = db.Column(db.Integer, default=0)
    employer_count = db.Column(db.Integer, default=0)
    top5_employer_share = db.Column(db.Float, default=0.0)  # 0.0–1.0
    metro_size_proxy = db.Column(db.Integer, default=0)  # all-SOC filings in metro/FY

    def to_dict(self):
        return {
            'id': self.id,
            'metro_code': self.metro_code,
            'metro_name': self.metro_name,
            'soc_code': self.soc_code,
            'fiscal_year': self.fiscal_year,
            'filing_count': self.filing_count,
            'employer_count': self.employer_count,
            'top5_employer_share': self.top5_employer_share,
            'metro_size_proxy': self.metro_size_proxy,
        }


class MetroOpportunity(db.Model):
    """Precomputed location opportunity score per metro (DE SOCs, last 3 FY)."""
    __tablename__ = 'metro_opportunity'
    __table_args__ = (
        db.Index('idx_metro_opp_code', 'metro_code', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    metro_code = db.Column(db.String(16), nullable=False)
    metro_name = db.Column(db.String(255), nullable=False)
    sponsor_density = db.Column(db.Float)       # 0–100 normalized
    concentration_penalty = db.Column(db.Float) # 0–100 (top5 share * 100)
    location_opportunity_score = db.Column(db.Float)  # density − penalty
    de_filing_count = db.Column(db.Integer, default=0)
    employer_count = db.Column(db.Integer, default=0)
    top5_employer_share = db.Column(db.Float, default=0.0)
    flag = db.Column(db.String(64), nullable=True)  # high_opportunity / high_competition
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'metro_code': self.metro_code,
            'metro_name': self.metro_name,
            'sponsor_density': self.sponsor_density,
            'concentration_penalty': self.concentration_penalty,
            'location_opportunity_score': self.location_opportunity_score,
            'de_filing_count': self.de_filing_count,
            'employer_count': self.employer_count,
            'top5_employer_share': self.top5_employer_share,
            'flag': self.flag,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ProfileSkill(db.Model):
    """A skill the candidate can actually claim. Seeded from Config, editable."""
    __tablename__ = 'profile_skill'
    __table_args__ = (
        db.Index('idx_profileskill_name', 'name', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))
    proficiency = db.Column(db.Integer, default=3)  # 1-5, drives skill weighting
    years = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'category': self.category,
            'proficiency': self.proficiency, 'years': self.years,
            'is_active': self.is_active,
        }


class ProfileExperience(db.Model):
    """Real work experience only. Never auto-populated with invented roles."""
    __tablename__ = 'profile_experience'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    location = db.Column(db.String(255))
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_current = db.Column(db.Boolean, default=False)
    employment_type = db.Column(db.String(50))  # full-time | internship | co-op
    description = db.Column(db.Text)
    skills_used = db.Column(db.Text)  # JSON list
    created_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'company': self.company,
            'location': self.location,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_current': self.is_current,
            'employment_type': self.employment_type,
            'description': self.description,
            'skills_used': _load_json(self.skills_used, []),
        }


class ProfileEducation(db.Model):
    __tablename__ = 'profile_education'

    id = db.Column(db.Integer, primary_key=True)
    degree = db.Column(db.String(50))   # MS | BS | PhD
    field = db.Column(db.String(255))
    school = db.Column(db.String(255))
    gpa = db.Column(db.Float, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_current = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id, 'degree': self.degree, 'field': self.field,
            'school': self.school, 'gpa': self.gpa,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_current': self.is_current,
        }


class ProfileProject(db.Model):
    __tablename__ = 'profile_project'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    tech_stack = db.Column(db.Text)  # JSON list
    url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'tech_stack': _load_json(self.tech_stack, []), 'url': self.url,
        }


class Preference(db.Model):
    """User-editable settings (locations, weights, schedule). JSON value."""
    __tablename__ = 'preference'
    __table_args__ = (
        db.Index('idx_pref_key', 'key', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    @property
    def parsed(self):
        return _load_json(self.value, None)

    def to_dict(self):
        return {'key': self.key, 'value': self.parsed,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None}


class WatchlistCompany(db.Model):
    __tablename__ = 'watchlist_company'
    __table_args__ = (
        db.Index('idx_watchlist_norm', 'normalized_name', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    normalized_name = db.Column(db.String(255), nullable=False)
    priority = db.Column(db.Integer, default=2)  # 1 = top target
    notes = db.Column(db.Text)
    # Evidence-based sponsorship info only; never assumed
    sponsorship_note = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'priority': self.priority,
            'notes': self.notes, 'sponsorship_note': self.sponsorship_note,
            'is_active': self.is_active,
        }


class Application(db.Model):
    """One application per job. Created only when the user acts."""
    __tablename__ = 'application'
    __table_args__ = (
        db.Index('idx_app_job', 'job_id'),
        db.Index('idx_app_status', 'status'),
        db.Index('idx_app_followup', 'next_followup_date'),
    )

    STATUSES = [
        'NEW', 'SHORTLISTED', 'APPLYING', 'APPLIED', 'PHONE_SCREEN',
        'INTERVIEW', 'TECHNICAL', 'FINAL', 'OFFER', 'REJECTED',
        'WITHDRAWN', 'EXPIRED',
    ]

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    company = db.Column(db.String(255))
    role = db.Column(db.String(255))
    application_url = db.Column(db.String(500))
    status = db.Column(db.String(24), default='NEW')
    date_applied = db.Column(db.DateTime, nullable=True)
    resume_version = db.Column(db.String(255))
    cover_letter = db.Column(db.Text)
    recruiter_name = db.Column(db.String(255))
    recruiter_email = db.Column(db.String(255))
    next_followup_date = db.Column(db.DateTime, nullable=True)
    followup_count = db.Column(db.Integer, default=0)
    interview_dates = db.Column(db.Text)  # JSON list of ISO strings
    notes = db.Column(db.Text)
    outcome = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    job = db.relationship('Job', backref=db.backref('applications', lazy='select'))

    def to_dict(self):
        return {
            'id': self.id, 'job_id': self.job_id, 'company': self.company,
            'role': self.role, 'application_url': self.application_url,
            'status': self.status,
            'date_applied': self.date_applied.isoformat() if self.date_applied else None,
            'resume_version': self.resume_version,
            'cover_letter': self.cover_letter,
            'recruiter_name': self.recruiter_name,
            'recruiter_email': self.recruiter_email,
            'next_followup_date': (
                self.next_followup_date.isoformat() if self.next_followup_date else None
            ),
            'followup_count': self.followup_count,
            'interview_dates': _load_json(self.interview_dates, []),
            'notes': self.notes, 'outcome': self.outcome,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ApplicationEvent(db.Model):
    __tablename__ = 'application_event'
    __table_args__ = (
        db.Index('idx_appevent_app', 'application_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'), nullable=False)
    event_type = db.Column(db.String(50))  # status_change | followup | note | interview
    from_status = db.Column(db.String(24))
    to_status = db.Column(db.String(24))
    detail = db.Column(db.Text)
    occurred_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'application_id': self.application_id,
            'event_type': self.event_type, 'from_status': self.from_status,
            'to_status': self.to_status, 'detail': self.detail,
            'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None,
        }


class Contact(db.Model):
    """A discovered professional contact for outreach (V3).

    Only legitimately public professional information is stored. Nothing here is
    ever fabricated: if a field is unknown it is left null and surfaced as
    UNKNOWN downstream. Each contact carries an evidence source URL and a
    confidence rather than an assumption.
    """
    __tablename__ = 'contact'
    __table_args__ = (
        db.Index('idx_contact_job', 'job_id'),
        db.Index('idx_contact_company', 'company'),
        db.Index('idx_contact_contacted', 'contact_status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    company = db.Column(db.String(255))

    # ---- Identity (evidence-backed; never guessed) ---------------------
    contact_type = db.Column(db.String(32))      # hiring_manager | technical_recruiter | ...
    contact_name = db.Column(db.String(255), nullable=True)
    contact_role = db.Column(db.String(255), nullable=True)   # "Engineering Manager"
    source = db.Column(db.String(100))           # e.g. 'company_team_page'
    source_url = db.Column(db.String(500), nullable=True)
    discovered_at = db.Column(db.DateTime, default=_utcnow)
    confidence = db.Column(db.String(16), default='UNKNOWN')  # HIGH|MEDIUM|LOW|UNKNOWN
    evidence = db.Column(db.Text)                # JSON list of evidence strings

    # ---- Professional contact channel (public evidence only) -------------
    email = db.Column(db.String(255), nullable=True)
    email_state = db.Column(db.String(24), default='NOT_FOUND')  # VERIFIED_PUBLIC|PUBLIC_UNVERIFIED|PATTERN_INFERRED|NOT_FOUND|UNKNOWN
    email_source = db.Column(db.String(255), nullable=True)
    email_verified = db.Column(db.Boolean, default=False)
    email_discovered_at = db.Column(db.DateTime, nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)

    # ---- Relevance + recommended type --------------------------------------
    contact_relevance_score = db.Column(db.Float, nullable=True)
    is_recommended = db.Column(db.Boolean, default=False)

    # ---- Outreach / contacted tracking (manual only; never auto-sends) -----
    contact_status = db.Column(db.String(20), default='NOT_CONTACTED')
    # NOT_CONTACTED | DRAFT_READY | CONTACTED | REPLIED | NO_RESPONSE |
    # FOLLOW_UP | NOT_RELEVANT
    contacted_at = db.Column(db.DateTime, nullable=True)
    contact_method = db.Column(db.String(16), nullable=True)  # EMAIL | LINKEDIN | FORM | OTHER
    message_draft = db.Column(db.Text, nullable=True)
    response_status = db.Column(db.String(24), nullable=True)
    follow_up_date = db.Column(db.DateTime, nullable=True)
    follow_up_count = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    job = db.relationship('Job', backref=db.backref('contacts', lazy='select'))

    def to_dict(self):
        return {
            'id': self.id, 'job_id': self.job_id, 'company': self.company,
            'contact_type': self.contact_type, 'contact_name': self.contact_name,
            'contact_role': self.contact_role, 'source': self.source,
            'source_url': self.source_url, 'confidence': self.confidence or 'UNKNOWN',
            'evidence': _load_json(self.evidence, []),
            'email': self.email, 'email_state': self.email_state or 'NOT_FOUND',
            'email_source': self.email_source,
            'email_verified': bool(self.email_verified),
            'email_discovered_at': (
                self.email_discovered_at.isoformat() if self.email_discovered_at else None
            ),
            'linkedin_url': self.linkedin_url,
            'contact_relevance_score': self.contact_relevance_score,
            'is_recommended': bool(self.is_recommended),
            'contact_status': self.contact_status or 'NOT_CONTACTED',
            'contacted_at': self.contacted_at.isoformat() if self.contacted_at else None,
            'contact_method': self.contact_method,
            'message_draft': self.message_draft,
            'response_status': self.response_status,
            'follow_up_date': (
                self.follow_up_date.isoformat() if self.follow_up_date else None
            ),
            'follow_up_count': self.follow_up_count or 0,
            'notes': self.notes,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Notification(db.Model):
    __tablename__ = 'notification'
    __table_args__ = (
        db.Index('idx_notif_read', 'is_read'),
        db.Index('idx_notif_created', 'created_at'),
        db.Index('idx_notif_dedupe', 'dedupe_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(50))
    # high_match | target_company | sponsorship_positive | followup_due |
    # saved_job_expiring | fresh_job
    title = db.Column(db.String(255))
    body = db.Column(db.Text)
    job_id = db.Column(db.Integer, nullable=True)
    application_id = db.Column(db.Integer, nullable=True)
    severity = db.Column(db.String(16), default='info')
    dedupe_key = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'kind': self.kind, 'title': self.title,
            'body': self.body, 'job_id': self.job_id,
            'application_id': self.application_id, 'severity': self.severity,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class SearchRun(db.Model):
    """One row per scrape run (manual or scheduled)."""
    __tablename__ = 'search_run'
    __table_args__ = (
        db.Index('idx_searchrun_started', 'started_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trigger = db.Column(db.String(20), default='manual')  # manual | scheduled
    status = db.Column(db.String(20), default='running')  # running|completed|failed
    sources = db.Column(db.Text)  # JSON list
    keywords = db.Column(db.Text)  # JSON list
    jobs_discovered = db.Column(db.Integer, default=0)
    jobs_accepted = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    avg_match = db.Column(db.Float, nullable=True)
    strong_matches = db.Column(db.Integer, default=0)
    excellent_matches = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    error_summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=_utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id, 'trigger': self.trigger, 'status': self.status,
            'sources': _load_json(self.sources, []),
            'keywords': _load_json(self.keywords, []),
            'jobs_discovered': self.jobs_discovered,
            'jobs_accepted': self.jobs_accepted,
            'duplicates': self.duplicates,
            'avg_match': self.avg_match,
            'strong_matches': self.strong_matches,
            'excellent_matches': self.excellent_matches,
            'error_count': self.error_count,
            'error_summary': self.error_summary,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class SourceRun(db.Model):
    """Per-source outcome inside a SearchRun — powers source quality metrics."""
    __tablename__ = 'source_run'
    __table_args__ = (
        db.Index('idx_sourcerun_run', 'search_run_id'),
        db.Index('idx_sourcerun_source', 'source'),
    )

    id = db.Column(db.Integer, primary_key=True)
    search_run_id = db.Column(db.Integer, db.ForeignKey('search_run.id'), nullable=True)
    source = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='success')  # success | failed
    jobs_discovered = db.Column(db.Integer, default=0)
    jobs_accepted = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    expired = db.Column(db.Integer, default=0)
    missing_apply_url = db.Column(db.Integer, default=0)
    avg_match = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=_utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id, 'search_run_id': self.search_run_id,
            'source': self.source, 'status': self.status,
            'jobs_discovered': self.jobs_discovered,
            'jobs_accepted': self.jobs_accepted,
            'duplicates': self.duplicates, 'expired': self.expired,
            'missing_apply_url': self.missing_apply_url,
            'avg_match': self.avg_match, 'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class ApplicationPrep(db.Model):
    """Generated application materials. Always reviewed by the user."""
    __tablename__ = 'application_prep'
    __table_args__ = (
        db.Index('idx_prep_job', 'job_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    resume_recommendation = db.Column(db.Text)
    resume_bullets = db.Column(db.Text)     # JSON list
    cover_letter = db.Column(db.Text)
    professional_summary = db.Column(db.Text)
    screening_questions = db.Column(db.Text)  # JSON list of {q, suggested, needs_review}
    highlight_skills = db.Column(db.Text)     # JSON list
    generated_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'job_id': self.job_id,
            'resume_recommendation': self.resume_recommendation,
            'resume_bullets': _load_json(self.resume_bullets, []),
            'cover_letter': self.cover_letter,
            'professional_summary': self.professional_summary,
            'screening_questions': _load_json(self.screening_questions, []),
            'highlight_skills': _load_json(self.highlight_skills, []),
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
        }


class UnparsedLocation(db.Model):
    __tablename__ = 'unparsed_location'
    __table_args__ = (
        db.Index('idx_unparsed_loc', 'location', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(255), nullable=False)
    hit_count = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))
