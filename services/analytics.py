"""Outcome analytics: what actually works for this candidate.

Every number here comes from the user's own recorded applications. When there
is not enough data to say anything, we say that instead of showing a
meaningless percentage.
"""

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
