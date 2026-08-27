from backend.app import app
from backend.models import Job, SearchRun, SourceRun
from services.briefing import top_jobs
from datetime import datetime, timezone, timedelta

with app.app_context():
    jobs = top_jobs(Job, limit=10, realistic=True)
    print('TOP 10 BRIEFING (by final_score):')
    for i, j in enumerate(jobs, 1):
        title = (j.title or '')[:40]
        print(
            i, 'final=', j.final_score, 'match=', j.candidate_match_score,
            'bucket=', j.freshness_bucket, 'scraped=', j.date_scraped,
            'posted=', j.date_posted, 'src=', j.source, title,
        )
    run = SearchRun.query.order_by(SearchRun.started_at.desc()).first()
    print('LAST RUN', run.started_at, run.status, 'discovered', run.jobs_discovered,
          'accepted', run.jobs_accepted, 'dupes', run.duplicates)
    for sr in SourceRun.query.filter_by(search_run_id=run.id).all():
        print(' SRC', sr.source, 'disc', sr.jobs_discovered, 'acc', sr.jobs_accepted,
              'dup', sr.duplicates, 'err', (sr.error_message or '')[:100])
    print('apply urls', Job.query.filter(Job.application_url.isnot(None), Job.application_url != '').count())
    print('verified', Job.query.filter(Job.application_url_status == 'verified').count())
    day = datetime.now(timezone.utc) - timedelta(hours=24)
    print('visible scraped 24h', Job.query.filter(
        Job.date_scraped >= day, Job.is_hidden == False, Job.is_expired == False,
        Job.duplicate_of_id.is_(None),
    ).count())
