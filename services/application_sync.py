"""One canonical application state, projected onto the Job row.

Two state models exist for historical reasons:

* ``Application.status`` — the real workflow, twelve states from NEW to OFFER.
* ``Job.application_status`` — a coarse legacy string the Jobs list filters and
  the stats endpoint group by.

They used to be written independently and only agreed on APPLIED: moving an
application to INTERVIEW or REJECTED left the job still reading ``applied``,
and editing a job directly left no Application at all. So the same job could
report two different states depending on which page you were looking at.

``Application`` is canonical now. ``Job.application_status``, ``Job.is_applied``
and ``Job.applied_date`` are *derived* — every mutation routes through
:func:`sync_job_from_application`, and an edit that starts on the Job side goes
through :func:`sync_application_from_job` so the canonical record moves too.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# The workflow, in order. Used for both the UI and to decide what a coarse
# legacy status maps to.
WORKFLOW = [
    'NEW',           # discovered, not yet triaged
    'SHORTLISTED',   # reviewed, worth applying to
    'APPLYING',      # materials being prepared
    'APPLIED',
    'PHONE_SCREEN',
    'INTERVIEW',
    'TECHNICAL',
    'FINAL',
    'OFFER',
]
TERMINAL = ['REJECTED', 'WITHDRAWN', 'EXPIRED']
ALL_STATUSES = WORKFLOW + TERMINAL

# Application status -> the coarse Job.application_status the UI filters on.
_TO_JOB_STATUS = {
    'NEW': 'not_applied',
    'SHORTLISTED': 'not_applied',
    'APPLYING': 'not_applied',
    'APPLIED': 'applied',
    'PHONE_SCREEN': 'interviewing',
    'INTERVIEW': 'interviewing',
    'TECHNICAL': 'interviewing',
    'FINAL': 'interviewing',
    'OFFER': 'offer',
    'REJECTED': 'rejected',
    'WITHDRAWN': 'withdrawn',
    'EXPIRED': 'withdrawn',
}

# The reverse direction, for an edit that starts on the Job row.
_FROM_JOB_STATUS = {
    'not_applied': 'NEW',
    'applied': 'APPLIED',
    'interviewing': 'INTERVIEW',
    'offer': 'OFFER',
    'rejected': 'REJECTED',
    'withdrawn': 'WITHDRAWN',
}

# States that mean the user has actually submitted something.
_SUBMITTED = {'APPLIED', 'PHONE_SCREEN', 'INTERVIEW', 'TECHNICAL', 'FINAL',
              'OFFER', 'REJECTED'}

JOB_STATUSES = sorted(set(_TO_JOB_STATUS.values()))


def job_status_for(application_status):
    return _TO_JOB_STATUS.get((application_status or '').upper(), 'not_applied')


def application_status_for(job_status):
    return _FROM_JOB_STATUS.get((job_status or '').lower(), 'NEW')


def is_submitted(application_status):
    return (application_status or '').upper() in _SUBMITTED


def sync_job_from_application(application, job=None):
    """Project the canonical application state onto its Job row.

    Call after every write to ``Application.status``. Returns the job, or None
    when the application has no job attached.
    """
    job = job or getattr(application, 'job', None)
    if job is None:
        return None

    status = (application.status or 'NEW').upper()
    job.application_status = job_status_for(status)
    job.is_applied = is_submitted(status)

    if is_submitted(status):
        # A submitted application always has a date; back-fill it rather than
        # leaving the job claiming it was applied to at no particular time.
        if application.date_applied is None:
            application.date_applied = datetime.now(timezone.utc)
        job.applied_date = application.date_applied
    else:
        # Moved back out of the applied states (e.g. withdrawn before sending).
        job.applied_date = application.date_applied

    return job


def sync_application_from_job(job, Application, session, status=None):
    """Move the canonical record when an edit starts on the Job row.

    Creates the Application if the user marks a job applied without one, which
    is how a job could previously end up ``applied`` with nothing in the
    tracker. Returns the Application, or None when the coarse status does not
    warrant creating one.
    """
    coarse = (status if status is not None else job.application_status) or 'not_applied'
    target = application_status_for(coarse)

    application = Application.query.filter_by(job_id=job.id).first()
    if application is None:
        if target == 'NEW':
            # Nothing to track yet; don't create empty tracker rows.
            job.application_status = 'not_applied'
            job.is_applied = False
            return None
        application = Application(
            job_id=job.id,
            company=job.company,
            role=job.title,
            application_url=job.application_url or job.job_url,
            status=target,
        )
        session.add(application)
        session.flush()
        logger.info(
            'Created application %s for job %s from a job-side status change',
            application.id, job.id,
        )
    elif application.status != target:
        application.status = target

    if is_submitted(target) and application.date_applied is None:
        application.date_applied = datetime.now(timezone.utc)

    sync_job_from_application(application, job)
    return application


def reconcile_all(session, Job, Application):
    """Repair rows that diverged before the sync existed.

    Applications win. A job flagged applied with no application row keeps its
    flag but gets a tracker entry, so nothing the user recorded is lost.
    """
    fixed = {'from_application': 0, 'orphan_applied': 0}

    for application in Application.query.all():
        job = application.job
        if job is None:
            continue
        expected = job_status_for(application.status)
        if job.application_status != expected or job.is_applied != is_submitted(
            application.status
        ):
            sync_job_from_application(application, job)
            fixed['from_application'] += 1

    tracked = {a.job_id for a in Application.query.with_entities(Application.job_id)}
    orphans = Job.query.filter(Job.is_applied.is_(True))
    if tracked:
        orphans = orphans.filter(Job.id.notin_(tracked))
    for job in orphans.all():
        sync_application_from_job(job, Application, session,
                                  status=job.application_status or 'applied')
        fixed['orphan_applied'] += 1

    session.commit()
    if any(fixed.values()):
        logger.info('Reconciled application state: %s', fixed)
    return fixed
