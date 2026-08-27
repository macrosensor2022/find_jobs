"""The daily briefing: "what should I apply to today?"

This is the single most important read path in the product. It answers the
question with real stored data only — if a field is unknown it is reported as
unknown rather than filled in.
"""

from datetime import datetime, timedelta, timezone

from config.settings import Config


def _utcnow():
    return datetime.now(timezone.utc)


def realistic_filters(Job):
    """The single definition of "a job I should realistically apply to".

    Returned as a list of SQLAlchemy conditions so both the briefing and the
    jobs list endpoint apply exactly the same rules.
    """
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
        (Job.freshness_bucket.is_(None)) | (Job.freshness_bucket != 'stale'),
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

    quality = get('job_quality_score')
    if quality is not None and quality < Config.MIN_QUALITY_FOR_RANKING:
        reasons.append(f'Quality score {quality} is below the ranking minimum '
                       f'({Config.MIN_QUALITY_FOR_RANKING}).')

    if get('freshness_bucket') == 'stale':
        reasons.append('Posting is stale (14+ days, not rediscovered).')

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

    # Pull a wider pool, then re-rank in Python with an explicit freshness boost.
    pool = (
        query.order_by(
            Job.final_score.desc().nullslast(),
            Job.candidate_match_score.desc().nullslast(),
        )
        .limit(max(limit * 8, 40))
        .all()
    )
    now = _utcnow()

    def _boost(job):
        score = float(job.final_score or 0)
        bucket = (job.freshness_bucket or 'unknown')
        bucket_bonus = {
            'hot': 22, 'fresh': 14, 'recent': 6, 'aging': -6,
            'old': -14, 'stale': -20, 'unknown': 0,
        }.get(bucket, 0)
        scraped = job.date_scraped
        scraped_bonus = 0
        if scraped is not None:
            if scraped.tzinfo is None:
                scraped = scraped.replace(tzinfo=timezone.utc)
            age_h = (now - scraped).total_seconds() / 3600.0
            if age_h <= 24:
                scraped_bonus = 15
            elif age_h <= 72:
                scraped_bonus = 8
            elif age_h <= 168:
                scraped_bonus = 2
        tier = job.role_tier
        tier_bonus = {1: 12, 2: 8, 3: -2}.get(tier, -6)
        return score + bucket_bonus + scraped_bonus + tier_bonus

    pool.sort(key=_boost, reverse=True)
    return pool[:limit]


def build_briefing(models, profile=None, limit=None, realistic=True):
    """Assemble the morning dashboard payload.

    `models` is a dict with the model classes so this stays importable without
    Flask: {'Job': Job, 'Application': Application, 'SearchRun': SearchRun,
            'WatchlistCompany': WatchlistCompany, 'Notification': Notification}
    """
    Job = models['Job']
    Application = models.get('Application')
    SearchRun = models.get('SearchRun')
    WatchlistCompany = models.get('WatchlistCompany')

    now = _utcnow()
    day_ago = now - timedelta(hours=24)

    base = applyable_query(Job)

    new_today = Job.query.filter(Job.date_scraped >= day_ago).count()
    strong = base.filter(
        Job.candidate_match_score >= Config.STRONG_MATCH_MIN
    ).count()
    excellent = base.filter(
        Job.candidate_match_score >= Config.EXCELLENT_MATCH_MIN
    ).count()
    sponsorship_positive = base.filter(Job.sponsorship_status == 'green').count()
    fresh = base.filter(Job.freshness_bucket == 'hot').count()

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
        },
        'thresholds': {
            'strong': Config.STRONG_MATCH_MIN,
            'excellent': Config.EXCELLENT_MATCH_MIN,
        },
        'last_run': last_run,
        'top_jobs': [job.to_dict() for job in jobs],
    }


def source_metrics(models, days=30):
    """Aggregate per-source quality metrics from recorded runs."""
    SourceRun = models['SourceRun']
    Job = models['Job']
    cutoff = _utcnow() - timedelta(days=days)

    rows = SourceRun.query.filter(SourceRun.started_at >= cutoff).all()
    by_source = {}
    for row in rows:
        entry = by_source.setdefault(row.source, {
            'source': row.source,
            'jobs_discovered': 0,
            'jobs_accepted': 0,
            'duplicates': 0,
            'expired': 0,
            'missing_apply_url': 0,
            'runs': 0,
            'failures': 0,
            'last_successful_run': None,
            'avg_match_samples': [],
        })
        entry['jobs_discovered'] += row.jobs_discovered or 0
        entry['jobs_accepted'] += row.jobs_accepted or 0
        entry['duplicates'] += row.duplicates or 0
        entry['expired'] += row.expired or 0
        entry['missing_apply_url'] += row.missing_apply_url or 0
        entry['runs'] += 1
        if row.status == 'failed':
            entry['failures'] += 1
        elif row.completed_at:
            iso = row.completed_at.isoformat()
            if not entry['last_successful_run'] or iso > entry['last_successful_run']:
                entry['last_successful_run'] = iso
        if row.avg_match is not None:
            entry['avg_match_samples'].append(row.avg_match)

    # Expired counts come from the current job table, not from run history.
    for source, entry in by_source.items():
        samples = entry.pop('avg_match_samples')
        entry['avg_match'] = round(sum(samples) / len(samples), 1) if samples else None
        entry['expired'] = Job.query.filter_by(source=source, is_expired=True).count()
        entry['stored_jobs'] = Job.query.filter_by(source=source).count()

    return sorted(by_source.values(), key=lambda e: -e['jobs_accepted'])
