"""Rescore every stored job with the current scoring engine.

Run after changing weights, role tiers, skills or sponsorship patterns:

    python scripts/rescore_all.py            # rescore everything
    python scripts/rescore_all.py --limit 50 # try it on a small batch first
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402  (initializes db + migrations)
from backend.models import Job, WatchlistCompany, db  # noqa: E402
from config.settings import Config  # noqa: E402
from services.dedupe import build_dedupe_key  # noqa: E402
from services.freshness import is_expired  # noqa: E402
from services.ranking import apply_to_model, score_job  # noqa: E402


def load_watchlist():
    rows = WatchlistCompany.query.filter_by(is_active=True).all()
    if rows:
        return [{'name': r.name, 'priority': r.priority} for r in rows]
    return [{'name': n, 'priority': 2} for n in Config.WATCHLIST_COMPANIES]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--batch', type=int, default=200)
    args = parser.parse_args()

    with app.app_context():
        watchlist = load_watchlist()
        query = Job.query.order_by(Job.id)
        if args.limit:
            query = query.limit(args.limit)
        jobs = query.all()
        print(f'Rescoring {len(jobs)} jobs...')

        eligible = hidden = failed = 0
        for index, job in enumerate(jobs, start=1):
            try:
                job.is_expired = is_expired(job.date_posted)
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
                    'salary_min': job.salary_min,
                    'salary_max': job.salary_max,
                    'salary_predicted': job.salary_predicted,
                    'description_partial': job.description_partial,
                    'application_url': job.application_url or job.job_url,
                    'application_url_status': job.application_url_status,
                    'verification_status': job.verification_status,
                    'is_expired': job.is_expired,
                    'duplicate_of_id': job.duplicate_of_id,
                    'competition_score': job.competition_score,
                }, watchlist=watchlist)
                apply_to_model(job, result)

                if not job.application_url and job.job_url:
                    job.application_url = job.job_url
                    job.application_url_status = job.application_url_status or 'unverified'

                if result['match']['eligible']:
                    eligible += 1
                    # Un-hide jobs that were only hidden by the old heuristics.
                    if job.is_hidden and not job.is_applied and not job.is_favorite:
                        job.is_hidden = False
                else:
                    job.is_hidden = True
                    hidden += 1
            except Exception as exc:  # keep going; one bad row must not stop the run
                failed += 1
                print(f'  ! job {job.id}: {exc}')

            if index % args.batch == 0:
                db.session.commit()
                print(f'  ...{index}/{len(jobs)}')

        db.session.commit()
        print(f'Done. eligible={eligible} hidden={hidden} failed={failed}')

        top = (
            Job.query.filter(Job.is_hidden.is_(False), Job.is_expired.is_(False))
            .order_by(Job.final_score.desc())
            .limit(10)
            .all()
        )
        print('\nTop 10 by final score:')
        for job in top:
            print(
                f'  {job.final_score:5.1f}  match={job.candidate_match_score:3d} '
                f'opp={job.opportunity_score:3d} q={job.job_quality_score:3d} '
                f'{job.sponsorship_status:7s} {job.title[:48]:48s} @ {job.company[:24]}'
            )


if __name__ == '__main__':
    main()
