"""The daily briefing: "what should I apply to today?"

This is the single most important read path in the product. It answers the
question with real stored data only — if a field is unknown it is reported as
unknown rather than filled in.
"""

from datetime import datetime, timedelta, timezone

from config.settings import Config


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(value):
    """UTC-aware ISO string. SQLite hands back naive datetimes, and a naive ISO
    string is parsed by the browser as *local* time — which renders every
    timestamp as "Just now" on a machine that is not on UTC.

    Defined here rather than imported from backend.models so this module stays
    importable without Flask.
    """
    if value is None:
        return None
    if getattr(value, 'tzinfo', None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def posting_age_cutoff(days, now=None):
    """The `date_posted` boundary for a max age in days."""
    return (now or _utcnow()) - timedelta(days=days)


def realistic_filters(Job, max_age_days=None, now=None):
    """The single definition of "a job I should realistically apply to".

    Returned as a list of SQLAlchemy conditions so both the briefing and the
    jobs list endpoint apply exactly the same rules.

    Age is measured against ``date_posted`` and a cutoff computed *now*. It
    used to be measured against the stored ``freshness_bucket`` column, which
    is only accurate as of the last time the job was scored — so a posting
    scored two weeks ago still carried ``bucket = 'fresh'`` and sailed through
    a "not stale" filter. Jobs whose posting date is unknown are kept: an
    unknown date is not evidence of age.
    """
    max_age_days = max_age_days or Config.MAX_JOB_AGE_DAYS
    cutoff = posting_age_cutoff(max_age_days, now=now)
    return [
        (Job.exp_hard_drop.is_(False)) | (Job.exp_hard_drop.is_(None)),
        (Job.location_blocked.is_(False)) | (Job.location_blocked.is_(None)),
        (Job.role_blocked.is_(False)) | (Job.role_blocked.is_(None)),
        (Job.sponsorship_status != 'red') | (Job.sponsorship_status.is_(None)),
        Job.job_quality_score >= Config.MIN_QUALITY_FOR_RANKING,
        (Job.is_applied.is_(False)) | (Job.is_applied.is_(None)),
        Job.duplicate_of_id.is_(None),
        # Prefer classified target-lane roles over mis-tagged SWE/growth titles
        Job.role_tier.isnot(None),
        (Job.date_posted.is_(None)) | (Job.date_posted >= cutoff),
    ]


def why_hidden(job, Job=None):
    """Explain why a job is not shown in the realistic apply list.

    Returns a list of human-readable reasons, each tied to a concrete stored
    value. No reason is invented; unknown fields simply do not produce one.
    """
    reasons = []
    if job is None:
        return reasons
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)

    if get('is_hidden'):
        reasons.append('Marked hidden / dismissed by you.')
    if get('is_applied'):
        reasons.append('Already applied.')
    if get('is_not_interested'):
        reasons.append('Marked not interested.')
    if get('is_expired'):
        reasons.append('Posting flagged as expired/unreachable.')
    if get('duplicate_of_id'):
        reasons.append('Duplicate of another stored job (kept once).')

    if get('exp_hard_drop'):
        reasons.append('Experience requirement is a hard drop for your profile.')
    if get('location_blocked'):
        reasons.append('Location is outside your target states.')
    if get('role_blocked'):
        reasons.append('Role family is off-target for your search.')
    if get('sponsorship_status') == 'red':
        reasons.append('Sponsorship status is red (no visa sponsorship).')

    if get('role_tier') is None and not get('role_blocked'):
        reasons.append(
            'Role could not be classified into a target tier, so it is kept '
            'out of the ranked list (check the Jobs page or Under the Radar).'
        )

    quality = get('job_quality_score')
    if quality is not None and quality < Config.MIN_QUALITY_FOR_RANKING:
        reasons.append(f'Quality score {quality} is below the ranking minimum '
                       f'({Config.MIN_QUALITY_FOR_RANKING}).')

    posted = get('date_posted')
    if posted is not None:
        if getattr(posted, 'tzinfo', None) is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age_days = int((_utcnow() - posted).total_seconds() // 86400)
        if age_days > Config.MAX_JOB_AGE_DAYS:
            reasons.append(
                f'Posted {age_days} days ago, past the '
                f'{Config.MAX_JOB_AGE_DAYS}-day maximum job age.'
            )

    if not reasons:
        reasons.append('This job passes the realistic filters — it should be visible.')
    return reasons


def applyable_query(Job, realistic=True):
    """Base query for jobs that are realistically worth applying to.

    With `realistic=False` only the hard exclusions apply (applied, dismissed,
    expired, hidden, duplicate) so the user can inspect the wider pool.
    """
    query = Job.query.filter(
        Job.is_hidden.is_(False),
        Job.is_applied.is_(False),
        Job.is_not_interested.is_(False),
        Job.is_expired.is_(False),
        Job.duplicate_of_id.is_(None),
    )
    if not realistic:
        return query
    for condition in realistic_filters(Job):
        query = query.filter(condition)
    return query


def top_jobs(Job, limit=None, min_score=None, realistic=True, prefer_fresh=True):
    """Ranked list of jobs to apply to, best first.

    When prefer_fresh=True (default for the morning briefing), recently posted
    and recently rediscovered jobs outrank stale high-score listings so the
    dashboard answers "what should I apply to *today*" instead of recycling
    last week's Greenhouse backlog.
    """
    limit = limit or Config.DAILY_TOP_N
    query = applyable_query(Job, realistic=realistic)
    if min_score:
        query = query.filter(Job.candidate_match_score >= min_score)

    # Morning briefing focuses on Tier 1–2 (analytics/DE/BI). Tier 3 ML/AI
    # research roles are stretch and were drowning out fresher target-lane jobs.
    max_tier = getattr(Config, 'BRIEFING_MAX_ROLE_TIER', 2)
    if prefer_fresh and max_tier:
        query = query.filter(Job.role_tier <= max_tier)

    if not prefer_fresh:
        return (
            query.order_by(
                Job.final_score.desc().nullslast(),
                Job.candidate_match_score.desc().nullslast(),
            )
            .limit(limit)
            .all()
        )

    # Today is scoped to postings young enough to still be worth an
    # application. A 40-day-old listing may still be a fine job, but it is not
    # an answer to "what should I apply to *today*" — it stays on the Jobs page.
    now = _utcnow()
    today_cutoff = posting_age_cutoff(Config.TODAY_MAX_AGE_DAYS, now=now)
    query = query.filter(
        (Job.date_posted.is_(None)) | (Job.date_posted >= today_cutoff)
    )

    # Pull a wider pool, then re-rank in Python with an explicit freshness boost.
    pool = (
        query.order_by(
            Job.final_score.desc().nullslast(),
            Job.candidate_match_score.desc().nullslast(),
        )
        .limit(max(limit * 8, 40))
        .all()
    )

    return sorted(pool, key=lambda j: -today_rank_score(j, now=now))[:limit]


# Ranking weights for Today. Freshness is deliberately strong enough that a
# 95-scoring 40-day-old posting loses to a 90-scoring one posted yesterday.
_FRESHNESS_BONUS = {
    'hot': 22, 'fresh': 18, 'recent': 10, 'aging': -4,
    'old': -14, 'stale': -24, 'unknown': -2,
}
_TIER_BONUS = {1: 12, 2: 8, 3: -2}
_RECOMMENDATION_BONUS = {'APPLY NOW': 8, 'APPLY': 4, 'WATCH': 0, 'SKIP': -12}


def today_rank_score(job, now=None):
    """Today's ordering: freshness × relevance × actionability.

    Deliberately *not* ``ORDER BY final_score DESC``. Today answers "what
    should I apply to today", so a fresh, well-matched, verifiably-applyable
    posting outranks a higher-scoring one that has been sitting for weeks.

    Every input is a real stored field:

    * posting age — from ``date_posted`` computed against *now*, never from
      scrape or rediscovery time
    * newly discovered — from ``first_seen``, which does not move when a job
      is rediscovered
    * role tier, recommendation, apply-URL verification
    """
    now = now or _utcnow()
    score = float(job.final_score or 0)

    _, bucket = job.live_freshness(now=now)
    score += _FRESHNESS_BONUS.get(bucket or 'unknown', 0)
    score += _TIER_BONUS.get(job.role_tier, -6)
    score += _RECOMMENDATION_BONUS.get(
        (job.application_recommendation or '').upper(), 0
    )

    # A genuinely new find deserves attention, but only a nudge — this bonus
    # keys off first_seen, so rediscovering an old posting cannot earn it.
    first_seen = job.first_seen or job.date_scraped
    if first_seen is not None:
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        age_h = (now - first_seen).total_seconds() / 3600.0
        if age_h <= 24:
            score += 6
        elif age_h <= 72:
            score += 3

    # An apply link we have actually checked is worth more than one we have not.
    if job.application_url_status == 'verified':
        score += 5
    elif job.application_url_status == 'dead':
        score -= 30

    return score


def build_briefing(models, db=None, profile=None, limit=None, realistic=True):
    """Assemble the morning dashboard payload.

    `models` is a dict with the model classes so this stays importable without
    Flask: {'Job': Job, 'Application': Application, 'SearchRun': SearchRun,
            'WatchlistCompany': WatchlistCompany, 'Notification': Notification,
            'Contact': Contact}
    `db` is the SQLAlchemy object used for the V3 industry/company radar
    aggregates; it is optional so the briefing stays testable without Flask.
    """
    Job = models['Job']
    Application = models.get('Application')
    SearchRun = models.get('SearchRun')
    WatchlistCompany = models.get('WatchlistCompany')

    now = _utcnow()
    day_ago = now - timedelta(hours=24)

    base = applyable_query(Job)

    # "New" means first discovered in the last 24h. `first_seen` never moves,
    # so rediscovering a month-old posting does not make it new — which is
    # exactly what counting on `date_scraped` used to do.
    new_today = base.filter(Job.first_seen >= day_ago).count()
    strong = base.filter(
        Job.candidate_match_score >= Config.STRONG_MATCH_MIN
    ).count()
    excellent = base.filter(
        Job.candidate_match_score >= Config.EXCELLENT_MATCH_MIN
    ).count()
    sponsorship_positive = base.filter(Job.sponsorship_status == 'green').count()
    # Genuinely posted in the last 24h, measured against the source's own
    # posting date rather than a stored bucket that may be weeks out of date.
    fresh = base.filter(Job.date_posted >= day_ago).count()
    today_eligible = base.filter(
        Job.role_tier.isnot(None),
        Job.role_tier <= getattr(Config, 'BRIEFING_MAX_ROLE_TIER', 2),
        (Job.date_posted.is_(None))
        | (Job.date_posted >= posting_age_cutoff(Config.TODAY_MAX_AGE_DAYS, now=now)),
    ).count()

    watchlist_names = []
    if WatchlistCompany is not None:
        watchlist_names = [
            row.name for row in
            WatchlistCompany.query.filter_by(is_active=True).all()
        ]
    target_company_matches = 0
    if watchlist_names:
        from sqlalchemy import or_
        target_company_matches = base.filter(
            or_(*[Job.company.ilike(f'%{name}%') for name in watchlist_names])
        ).count()

    followups_due = 0
    active_applications = 0
    if Application is not None:
        followups_due = Application.query.filter(
            Application.next_followup_date.isnot(None),
            Application.next_followup_date <= now,
            Application.status.notin_(['REJECTED', 'WITHDRAWN', 'OFFER', 'EXPIRED']),
        ).count()
        active_applications = Application.query.filter(
            Application.status.notin_(['REJECTED', 'WITHDRAWN', 'EXPIRED'])
        ).count()

    last_run = None
    if SearchRun is not None:
        run = SearchRun.query.order_by(SearchRun.started_at.desc()).first()
        if run:
            last_run = run.to_dict()

    jobs = top_jobs(Job, limit=limit, realistic=realistic)

    # "5 APPLY NOW / 4 APPLY / 3 WATCH" for the Today header, counted over the
    # same pool Today ranks from.
    recommendation_counts = {'APPLY NOW': 0, 'APPLY': 0, 'WATCH': 0, 'SKIP': 0}
    for job in jobs:
        action = (job.application_recommendation or 'WATCH').upper()
        if action in recommendation_counts:
            recommendation_counts[action] += 1

    # V3 — Today Command Center sections (industry radar, under-the-radar,
    # companies hiring, contact these people).
    try:
        radar = today_radar(models, db, limit=6)
    except Exception:
        radar = {'industry_radar': [], 'under_the_radar_jobs': [], 'companies_hiring': []}
    try:
        Contact = models.get('Contact')
        contacts = contact_today(db, Contact, limit=10)
    except Exception:
        contacts = []

    return {
        'generated_at': now.isoformat(),
        'greeting_name': (profile.name.split()[0] if profile and profile.name else None),
        'counts': {
            'new_today': new_today,
            'strong_matches': strong,
            'excellent_matches': excellent,
            'target_company_matches': target_company_matches,
            'sponsorship_positive': sponsorship_positive,
            'posted_last_24h': fresh,
            'followups_due': followups_due,
            'active_applications': active_applications,
            'applyable_total': base.count(),
            'today_eligible': today_eligible,
        },
        'recommendation_counts': recommendation_counts,
        'thresholds': {
            'strong': Config.STRONG_MATCH_MIN,
            'excellent': Config.EXCELLENT_MATCH_MIN,
            'today_max_age_days': Config.TODAY_MAX_AGE_DAYS,
            'max_job_age_days': Config.MAX_JOB_AGE_DAYS,
        },
        'last_run': last_run,
        'top_jobs': [job.to_dict(summary=True) for job in jobs],
        # V3 — Today Command Center
        'industry_radar': radar.get('industry_radar', []),
        'under_the_radar_jobs': radar.get('under_the_radar_jobs', []),
        'companies_hiring': radar.get('companies_hiring', []),
        'contact_these_people': contacts,
    }


# A scrape source can store jobs under a different `source` value than the one
# it runs as. Only the ATS fan-out does this today.
_SOURCE_ALIASES = {
    'ats': ['ats', 'greenhouse', 'lever', 'ashby', 'smartrecruiters'],
}


def source_metrics(models, days=30):
    """Per-source health, covering every registered source.

    Sources that never ran in the window still appear, so a board that has
    silently stopped producing — or that is switched off, or missing its API
    key — is visible rather than simply absent from the list.
    """
    from services import source_health

    SourceRun = models['SourceRun']
    Job = models['Job']
    now = _utcnow()
    cutoff = now - timedelta(days=days)

    by_source = {}

    def _entry(name):
        if name not in by_source:
            status = source_health.source_status(name)
            by_source[name] = {
                'source': name,
                'label': status['label'] or name,
                'kind': status.get('kind'),
                'configured': status['enabled'],
                'disabled_reason': status['reason'],
                'signup_url': status.get('signup_url'),
                'missing_credentials': status.get('missing') or [],
                'jobs_discovered': 0,
                'jobs_matched': 0,
                'jobs_accepted': 0,
                'jobs_rejected': 0,
                'duplicates': 0,
                'expired': 0,
                'missing_apply_url': 0,
                'runs': 0,
                'failures': 0,
                'last_run_at': None,
                'last_successful_run': None,
                'last_status': None,
                'last_message': None,
                'last_duration_seconds': None,
                'rejected_breakdown': {},
                'avg_match_samples': [],
            }
        return by_source[name]

    # Seed every registered source so nothing can be silently missing.
    for name in source_health.registry():
        _entry(name)

    rows = (
        SourceRun.query
        .filter(SourceRun.started_at >= cutoff)
        .order_by(SourceRun.started_at.asc())
        .all()
    )
    for row in rows:
        entry = _entry(row.source)
        entry['jobs_discovered'] += row.jobs_discovered or 0
        entry['jobs_matched'] += row.jobs_matched or 0
        entry['jobs_accepted'] += row.jobs_accepted or 0
        entry['jobs_rejected'] += row.jobs_rejected or 0
        entry['duplicates'] += row.duplicates or 0
        entry['missing_apply_url'] += row.missing_apply_url or 0
        entry['runs'] += 1
        for reason, count in (row.to_dict().get('rejected_breakdown') or {}).items():
            entry['rejected_breakdown'][reason] = (
                entry['rejected_breakdown'].get(reason, 0) + count
            )
        # Rows are ordered oldest-first, so the last assignment wins.
        entry['last_status'] = row.status
        # Only surface a message when the last run needs explaining. Carrying
        # an old "returned no listings" note onto a source that has since run
        # fine reads as a live warning when it is not.
        entry['last_message'] = (
            (row.message or row.error_message)
            if row.status in (source_health.STATUS_EMPTY,
                              source_health.STATUS_FAILED,
                              source_health.STATUS_DISABLED)
            else None
        )
        entry['last_duration_seconds'] = row.duration_seconds
        if row.started_at:
            entry['last_run_at'] = _iso(row.started_at)
        if row.status == source_health.STATUS_FAILED:
            entry['failures'] += 1
        elif row.status in (source_health.STATUS_SUCCESS, source_health.STATUS_EMPTY):
            if row.completed_at:
                entry['last_successful_run'] = _iso(row.completed_at)
        if row.avg_match is not None:
            entry['avg_match_samples'].append(row.avg_match)

    for name, entry in by_source.items():
        samples = entry.pop('avg_match_samples')
        entry['avg_match'] = round(sum(samples) / len(samples), 1) if samples else None
        # The ATS fan-out stores each job under its actual board
        # (greenhouse / lever / ashby), so counting `source == 'ats'` would
        # always report zero stored jobs for a source that is working fine.
        stored_sources = _SOURCE_ALIASES.get(name, [name])
        entry['expired'] = Job.query.filter(
            Job.source.in_(stored_sources), Job.is_expired.is_(True)
        ).count()
        entry['stored_jobs'] = Job.query.filter(
            Job.source.in_(stored_sources)
        ).count()

        if not entry['configured']:
            entry['health'] = 'Disabled'
            entry['health_state'] = 'disabled'
        elif entry['runs'] == 0:
            entry['health'] = 'Never run'
            entry['health_state'] = 'idle'
        else:
            last_ok = None
            if entry['last_successful_run']:
                last_ok = datetime.fromisoformat(entry['last_successful_run'])
            entry['health'] = source_health.health_label(
                entry['last_status'], entry['jobs_discovered'], last_ok, now=now,
            )
            entry['health_state'] = {
                'Healthy': 'healthy', 'Failing': 'failing',
                'No results': 'warning', 'Disabled': 'disabled',
                'Running': 'running',
            }.get(entry['health'], 'warning')

    # Failing first, then disabled, then by how much each source contributes.
    order = {'failing': 0, 'warning': 1, 'disabled': 2, 'idle': 3, 'healthy': 4}
    return sorted(
        by_source.values(),
        key=lambda e: (order.get(e['health_state'], 5), -e['jobs_accepted']),
    )


# =============================================================================
# V3 — Today Command Center intelligence (Part 19)
# =============================================================================

def today_radar(models, db, limit=6):
    """Industry + under-the-radar + company sections for the Today view.

    All figures come from real stored jobs. Competition is UNKNOWN unless
    legitimate evidence exists; nothing is fabricated.
    """
    from services.analytics import industry_radar, employer_radar

    Job = models['Job']
    try:
        radar = industry_radar(db, Job, limit=limit)
    except Exception:
        radar = []

    # Under-the-radar opportunities (jobs, not industries).
    utr = applyable_query(Job).filter(
        Job.under_the_radar.is_(True)
    ).order_by(
        Job.final_score.desc().nullslast()
    ).limit(limit).all()

    companies = []
    try:
        companies = employer_radar(db, Job, days=30, limit=limit)['active_employers']
    except Exception:
        companies = []

    return {
        'industry_radar': radar,
        'under_the_radar_jobs': [j.to_dict(summary=True) for j in utr],
        'companies_hiring': companies,
    }


def contact_today(db, Contact, limit=10):
    """Rank recommended contacts for the 'Contact These People' Today section.

    Ranked by contact relevance + job priority + freshness. Only jobs whose
    stored recommended contact is legitimate are included.
    """
    if Contact is None:
        return []

    rows = Contact.query.filter(
        Contact.contact_status.notin_(['NOT_RELEVANT']),
        Contact.is_recommended.is_(True),
    ).order_by(
        Contact.contact_relevance_score.desc().nullslast()
    ).limit(limit * 2).all()

    out = []
    for c in rows:
        job = c.job
        if job is None or job.is_hidden or job.is_expired or job.duplicate_of_id:
            continue
        out.append({
            'job_id': job.id,
            'title': job.title,
            'company': c.company or job.company,
            'match_score': job.candidate_match_score,
            'application_priority': job.application_priority_score,
            'freshness_bucket': job.freshness_bucket,
            'contact': c.to_dict(),
        })
    out.sort(
        key=lambda r: (r.get('contact') or {}).get('contact_relevance_score') or 0,
        reverse=True,
    )
    return out[:limit]
