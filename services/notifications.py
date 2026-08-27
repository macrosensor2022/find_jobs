"""Notification generation from real stored state.

Every notification points at an actual job or application. Nothing is emitted
speculatively, and each one is de-duplicated by a stable key so a daily run
does not repeat yesterday's alerts.
"""

from datetime import datetime, timedelta, timezone

from config.settings import Config


def _add(db, Notification, kind, title, body, dedupe_key, severity='info',
         job_id=None, application_id=None):
    if Notification.query.filter_by(dedupe_key=dedupe_key).first():
        return False
    db.session.add(Notification(
        kind=kind, title=title, body=body, dedupe_key=dedupe_key,
        severity=severity, job_id=job_id, application_id=application_id,
    ))
    return True


def generate_notifications(db, Job, Application, Notification, WatchlistCompany):
    """Create notifications for anything that needs attention. Returns count."""
    now = datetime.now(timezone.utc)
    created = 0

    base = Job.query.filter(
        Job.is_hidden.is_(False),
        Job.is_expired.is_(False),
        Job.is_applied.is_(False),
        Job.is_not_interested.is_(False),
    )

    for job in base.filter(
        Job.candidate_match_score >= Config.EXCELLENT_MATCH_MIN
    ).order_by(Job.final_score.desc()).limit(25).all():
        created += _add(
            db, Notification, 'high_match',
            f'{job.candidate_match_score}% match: {job.title}',
            f'{job.company} — {job.location or "location unknown"}',
            dedupe_key=f'high_match:{job.id}', severity='high', job_id=job.id,
        )

    watchlist = [row.name for row in
                 WatchlistCompany.query.filter_by(is_active=True).all()]
    if watchlist:
        from sqlalchemy import or_
        for job in base.filter(
            or_(*[Job.company.ilike(f'%{name}%') for name in watchlist]),
            Job.candidate_match_score >= 50,
        ).order_by(Job.final_score.desc()).limit(25).all():
            created += _add(
                db, Notification, 'target_company',
                f'Target company hiring: {job.company}',
                f'{job.title} — {job.candidate_match_score}% match',
                dedupe_key=f'target_company:{job.id}', severity='high',
                job_id=job.id,
            )

    for job in base.filter(
        Job.sponsorship_status == 'green',
        Job.candidate_match_score >= 60,
    ).order_by(Job.final_score.desc()).limit(15).all():
        created += _add(
            db, Notification, 'sponsorship_positive',
            f'Sponsorship-positive: {job.title}',
            f'{job.company} — {job.sponsorship_reason or "sponsorship stated"}',
            dedupe_key=f'sponsorship:{job.id}', severity='high', job_id=job.id,
        )

    for job in base.filter(
        Job.freshness_bucket == 'hot',
        Job.candidate_match_score >= Config.STRONG_MATCH_MIN,
    ).order_by(Job.final_score.desc()).limit(15).all():
        created += _add(
            db, Notification, 'fresh_job',
            f'Posted today: {job.title}',
            f'{job.company} — {job.candidate_match_score}% match',
            dedupe_key=f'fresh:{job.id}:{now.date().isoformat()}',
            job_id=job.id,
        )

    for application in Application.query.filter(
        Application.next_followup_date.isnot(None),
        Application.next_followup_date <= now,
        Application.status.notin_(['REJECTED', 'WITHDRAWN', 'OFFER', 'EXPIRED']),
    ).all():
        due = application.next_followup_date.date().isoformat()
        created += _add(
            db, Notification, 'followup_due',
            f'Follow up: {application.company}',
            f'{application.role} — applied '
            f'{application.date_applied.date().isoformat() if application.date_applied else "date unknown"}',
            dedupe_key=f'followup:{application.id}:{due}',
            severity='warning', application_id=application.id,
        )

    soon = now + timedelta(days=3)
    for job in Job.query.filter(
        Job.is_favorite.is_(True),
        Job.is_applied.is_(False),
        Job.date_posted.isnot(None),
    ).all():
        posted = job.date_posted
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        expiry = posted + timedelta(days=Config.JOB_EXPIRY_DAYS)
        if now < expiry <= soon:
            created += _add(
                db, Notification, 'saved_job_expiring',
                f'Saved job closing soon: {job.title}',
                f'{job.company} — expected to age out on {expiry.date().isoformat()}',
                dedupe_key=f'expiring:{job.id}', severity='warning', job_id=job.id,
            )

    if created:
        db.session.commit()
    return created
