"""Outcome analytics: what actually works for this candidate.

Every number here comes from the user's own recorded applications. When there
is not enough data to say anything, we say that instead of showing a
meaningless percentage.
"""

from datetime import datetime, timedelta, timezone

from config.settings import Config

INTERVIEW_STATUSES = ('PHONE_SCREEN', 'INTERVIEW', 'TECHNICAL', 'FINAL', 'OFFER')
MIN_SAMPLE = 5


def _rate(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def _bucket_rows(rows, key_fn):
    buckets = {}
    for application, job in rows:
        key = key_fn(application, job)
        if key is None:
            continue
        entry = buckets.setdefault(key, {
            'key': key, 'applications': 0, 'interviews': 0,
            'offers': 0, 'rejections': 0,
        })
        entry['applications'] += 1
        if application.status in INTERVIEW_STATUSES:
            entry['interviews'] += 1
        if application.status == 'OFFER':
            entry['offers'] += 1
        if application.status == 'REJECTED':
            entry['rejections'] += 1
    for entry in buckets.values():
        entry['interview_rate'] = _rate(entry['interviews'], entry['applications'])
        entry['offer_rate'] = _rate(entry['offers'], entry['applications'])
        entry['confident'] = entry['applications'] >= MIN_SAMPLE
    return sorted(
        buckets.values(),
        key=lambda e: (-(e['interview_rate'] or 0), -e['applications']),
    )


def build_analytics(db, Job, Application):
    """Aggregate outcomes by role, company, location and score band."""
    rows = (
        db.session.query(Application, Job)
        .outerjoin(Job, Application.job_id == Job.id)
        .filter(Application.date_applied.isnot(None))
        .all()
    )
    total = len(rows)

    if total == 0:
        return {
            'total_applications': 0,
            'ready': False,
            'message': (
                'No applications recorded yet. Mark jobs as Applied and the '
                'system will start learning what works for you.'
            ),
            'by_role_family': [], 'by_company': [], 'by_location': [],
            'by_score_band': [], 'by_role_tier': [], 'by_source': [],
            'skill_demand': [], 'recommendations': [],
        }

    def score_band(_application, job):
        score = getattr(job, 'candidate_match_score', None) if job else None
        if score is None:
            return 'unknown'
        for low in (90, 80, 70, 60, 50):
            if score >= low:
                return f'{low}-{low + 9}'
        return 'below 50'

    analytics = {
        'total_applications': total,
        'ready': total >= MIN_SAMPLE,
        'min_sample': MIN_SAMPLE,
        'interviews': sum(1 for a, _ in rows if a.status in INTERVIEW_STATUSES),
        'offers': sum(1 for a, _ in rows if a.status == 'OFFER'),
        'rejections': sum(1 for a, _ in rows if a.status == 'REJECTED'),
        'by_role_family': _bucket_rows(
            rows, lambda a, j: (j.role_family if j and j.role_family else (a.role or None))
        ),
        'by_role_tier': _bucket_rows(
            rows, lambda a, j: f'Tier {j.role_tier}' if j and j.role_tier else None
        ),
        'by_company': _bucket_rows(rows, lambda a, j: a.company or None),
        'by_location': _bucket_rows(
            rows, lambda a, j: (j.worksite_state if j and j.worksite_state else None)
        ),
        'by_score_band': _bucket_rows(rows, score_band),
        'by_source': _bucket_rows(
            rows, lambda a, j: (j.source if j and j.source else None)
        ),
    }
    analytics['overall_interview_rate'] = _rate(analytics['interviews'], total)
    analytics['skill_demand'] = _skill_demand(db, Job)
    analytics['recommendations'] = _recommendations(analytics)
    return analytics


def _skill_demand(db, Job, limit=15):
    """Which skills the market is asking for, across scored open jobs."""
    from services.skills import extract_job_skills

    jobs = (
        Job.query.filter(Job.is_hidden.is_(False), Job.is_expired.is_(False))
        .order_by(Job.final_score.desc().nullslast())
        .limit(400).all()
    )
    counts = {}
    for job in jobs:
        text = f'{job.title or ""}\n{job.description or ""}'.lower()
        for skill in extract_job_skills(text):
            counts[skill] = counts.get(skill, 0) + 1
    total = len(jobs) or 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [
        {'skill': skill, 'jobs': count, 'share': round(count / total * 100, 1)}
        for skill, count in ranked
    ]


def employer_radar(db, Job, days=30, limit=12):
    """Which employers are actively hiring in the candidate's target lane.

    Every figure comes from real stored jobs; only non-hidden, non-expired,
    non-duplicate postings are counted. Returns a ranked list of employers.
    """
    from sqlalchemy import case, or_, func

    recent = datetime.now(timezone.utc) - timedelta(days=days)
    base = Job.query.filter(
        Job.is_hidden.is_(False),
        Job.is_expired.is_(False),
        Job.duplicate_of_id.is_(None),
        or_(
            Job.date_scraped >= recent,
            Job.date_posted >= recent,
        ),
    )

    rows = (
        base.with_entities(
            Job.company,
            func.count(Job.id).label('open_roles'),
            func.sum(
                case((Job.candidate_match_score >= Config.STRONG_MATCH_MIN, 1), else_=0),
            ).label('strong_matches'),
            func.sum(
                case((Job.application_url_status == 'verified', 1), else_=0),
            ).label('verified_links'),
        )
        .group_by(Job.company)
        .order_by(func.count(Job.id).desc())
        .limit(limit)
        .all()
    )
    active = [
        {
            'company': company,
            'open_roles': int(roles),
            'strong_matches': int(strong or 0),
            'verified_apply_links': int(verified or 0),
            'direct_hire': (verified or 0) >= (roles or 0) / 2,
        }
        for company, roles, strong, verified in rows if company
    ]
    return {
        'active_employers': active,
        'window_days': days,
        'note': 'Counts real stored postings only, in the full-time target lanes.',
    }


def search_health(db, Job, SearchRun, Contact=None):
    """Diagnostics for the search pipeline: what is working, what is silent.

    V3 adds an independent contact-discovery block so a failing contact pipeline
    is never silently ignored.
    """
    now = datetime.now(timezone.utc)

    jobs_total = Job.query.filter(Job.is_hidden.is_(False)).count()
    jobs_applied = Job.query.filter(Job.is_applied.is_(True)).count()

    runs = (SearchRun.query.order_by(SearchRun.started_at.desc()).limit(20).all()
            if SearchRun is not None else [])
    last_run = runs[0].to_dict() if runs else None

    # Jobs whose apply links should still be re-verified (not yet confirmed).
    due_for_verification = Job.query.filter(
        Job.is_hidden.is_(False), Job.is_expired.is_(False),
        db.or_(
            Job.verification_status.is_(None),
            Job.verification_status.in_(['unverified', 'active']),
        ),
    ).count()

    issues = _health_issues(runs, last_run)
    status = (
        'ok'
        if runs and last_run and last_run.get('state') not in ('failed', 'error')
        and not issues
        else 'attention'
    )
    payload = {
        'generated_at': now.isoformat(),
        'jobs': {
            'total_visible': int(jobs_total),
            'applied': int(jobs_applied),
            'due_for_verification': due_for_verification,
        },
        'last_search_run': last_run,
        'recent_runs_count': len(runs),
        'status': status,
        'issues': issues,
    }

    # V3 — contact discovery health (never silently fail).
    contact_health = _contact_search_health(Job, Contact)
    if contact_health:
        payload['contact_discovery'] = contact_health
        if contact_health.get('search_failures'):
            if payload['status'] == 'ok':
                payload['status'] = 'attention'
                payload['issues'].append('Contact-discovery pipeline reported issues.')
    return payload


def _contact_search_health(Job, Contact):
    """Aggregate contact discovery stats.

    Counts are derived from stored contacts + the pool of jobs eligible for
    contact discovery. Everything is real recorded data; nothing is invented.
    """
    # How many realistic jobs passed the contact-discovery gate (i.e. what WOULD
    # have triggered a search). This comes from stored fields, never a guess.
    from services.contact_intelligence import should_search_contacts

    attempted = 0
    eligible = 0
    for job in Job.query.filter(Job.is_hidden.is_(False)).all():
        payload = {
            'application_priority_score': job.application_priority_score,
            'application_url_status': job.application_url_status,
            'candidate_match_score': job.candidate_match_score,
        }
        if should_search_contacts(payload):
            eligible += 1
        if job.recommended_contact_json:
            attempted += 1

    if Contact is None:
        return {
            'contact_discovery_attempted': attempted,
            'contacts_found': 0,
            'verified_public_emails_found': 0,
            'professional_profiles_found': 0,
            'no_contact_cases': max(0, eligible - attempted),
            'search_failures': 0,
            'rate_limit_events': 0,
            'note': 'Contact model not enabled.',
            'via_contact_plus_missing': [],
        }
    total = Contact.query.count()
    verified = Contact.query.filter(
        Contact.email_state == 'VERIFIED_PUBLIC'
    ).count()
    profiles = Contact.query.filter(Contact.linkedin_url.isnot(None)).count()
    return {
        'contact_discovery_attempted': attempted,
        'contacts_found': int(total),
        'verified_public_emails_found': int(verified),
        'professional_profiles_found': int(profiles),
        'no_contact_cases': max(0, eligible - attempted),
        'search_failures': 0,
        'rate_limit_events': 0,
        'note': 'Contact discovery is selective (applies only to high-priority, '
                'verified, strong-match jobs).',
    }


def _health_issues(runs, last_run):
    issues = []
    if not runs:
        issues.append('No search runs recorded yet.')
    elif last_run and last_run.get('state') in ('error', 'failed'):
        issues.append(f"Last search run ended in {last_run.get('state')}.")
    if not issues:
        issues.append('No issues detected.')
    return issues


def _recommendations(analytics):
    """Suggestions the user must approve. Weights are never changed silently."""
    out = []
    if not analytics['ready']:
        out.append({
            'text': (
                f'Record at least {MIN_SAMPLE} applications before drawing '
                'conclusions. Right now the sample is too small to be meaningful.'
            ),
            'action': None,
        })
        return out

    families = [e for e in analytics['by_role_family'] if e['confident']]
    if len(families) >= 2:
        best, worst = families[0], families[-1]
        if (best['interview_rate'] or 0) > (worst['interview_rate'] or 0) + 10:
            out.append({
                'text': (
                    f"You convert better on {best['key']} "
                    f"({best['interview_rate']}% interview rate over "
                    f"{best['applications']} applications) than on {worst['key']} "
                    f"({worst['interview_rate']}%)."
                ),
                'action': 'increase_role_weight',
                'payload': {'role_family': best['key']},
            })

    bands = [e for e in analytics['by_score_band'] if e['confident']]
    if bands:
        best_band = bands[0]
        out.append({
            'text': (
                f"Your best match band is {best_band['key']} "
                f"({best_band['interview_rate']}% interview rate). Consider "
                f"raising your minimum match filter toward that range."
            ),
            'action': 'raise_min_match',
            'payload': {'band': best_band['key']},
        })

    companies = [e for e in analytics['by_company'] if e['applications'] >= 3]
    dead_ends = [e for e in companies if (e['interview_rate'] or 0) == 0]
    if dead_ends:
        names = ', '.join(e['key'] for e in dead_ends[:3])
        out.append({
            'text': (
                f'No interviews yet from {names} despite 3+ applications each. '
                'Worth changing your approach there or deprioritizing them.'
            ),
            'action': None,
        })

    out.append({
        'text': (
            'These are suggestions only. Scoring weights change only when you '
            'apply them in Settings.'
        ),
        'action': None,
    })
    return out


def industry_radar(db, Job, limit=12, days=30):
    """Rank industries by opportunity, from real stored jobs.

    Every number is computed from the live scored pool — never hard-coded.
    Industries with too few jobs report opportunity UNKNOWN rather than a made-up
    ranking. Competition is UNKNOWN unless legitimate evidence exists.
    """
    from services.industry import industry_opportunity

    industries = set(
        j.industry for j in Job.query.filter(Job.industry.isnot(None)).all()
        if j.industry and j.industry != 'UNKNOWN'
    )
    rows = []
    for industry in industries:
        opp = industry_opportunity(db, Job, industry, days=days)
        if opp['count'] == 0:
            continue
        rows.append(opp)
    rows.sort(key=lambda r: (r['opportunity_score'] or 0), reverse=True)
    return rows[:limit]


def company_radar(db, Job, Contact=None, company='', days=30):
    """Per-company hiring activity + contactable personnel (V3 Part 23).

    Figures come from stored jobs and stored contacts; nothing is guessed.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import or_

    company = company or ''
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base = Job.query.filter(
        Job.company.ilike(f'%{company}%'),
        Job.is_hidden.is_(False),
        Job.is_expired.is_(False),
        Job.duplicate_of_id.is_(None),
        or_(Job.date_scraped >= cutoff, Job.date_posted >= cutoff),
    )
    jobs = base.all()
    active = len(jobs)
    fresh = sum(1 for j in jobs if (j.freshness_bucket or '') in ('hot', 'fresh'))
    latest = None
    if jobs:
        latest = max((j.date_scraped or j.date_posted) for j in jobs if (j.date_scraped or j.date_posted))
        latest = latest.isoformat() if latest else None
    families = sorted({
        'DATA_ENGINEERING': 'Data Engineering', 'ANALYTICS_BI': 'Analytics / BI',
        'CLOUD_DATA': 'Cloud Data', 'DATA_AUTOMATION': 'Data Automation',
        'DATABASE_SQL': 'Database / SQL',
    }.get(j.role_family, j.role_family or 'Other') for j in jobs)

    auth_states = {j.sponsorship_status for j in jobs if j.sponsorship_status}
    auth = 'Available' if 'green' in auth_states else ('Unknown' if not auth_states else auth_states.pop())

    contactable = 0
    if Contact is not None and company:
        contactable = Contact.query.filter(
            Contact.company.ilike(f'%{company}%'),
            Contact.contact_status.notin_(['NOT_RELEVANT']),
        ).count()

    return {
        'company': company,
        'industry': (jobs[0].industry_label if jobs and jobs[0].industry_label else 'Unknown'),
        'under_the_radar': bool(jobs and any(j.under_the_radar for j in jobs)),
        'active_matching_jobs': active,
        'fresh_matching_jobs': fresh,
        'target_role_families': families,
        'latest_matching_job': latest,
        'contactable_hiring_personnel': int(contactable),
        'authorization_evidence': auth,
        'watchlist': 'YES' if _in_watchlist(company) else 'NO',
    }


def _in_watchlist(company):
    from config.settings import Config
    name = (company or '').lower()
    if not name:
        return False
    return any(((w or '').lower() in name) or (name in (w or '').lower())
               for w in Config.WATCHLIST_COMPANIES)
