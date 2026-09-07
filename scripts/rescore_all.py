"""Rescore every stored job with the current scoring engine.

Run after changing weights, role tiers, skills or sponsorship patterns:

    python scripts/rescore_all.py               # rescore everything
    python scripts/rescore_all.py --limit 50    # try it on a small batch first
    python scripts/rescore_all.py --missing     # only rows missing new fields
    python scripts/rescore_all.py --no-industry # skip industry classification

Shares one code path with the app's startup rescore and the scheduler
(``services/rescore.py``), so a job scored here is identical to one scored by
the running server.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_  # noqa: E402

from backend.app import app  # noqa: E402  (initializes db + migrations)
from backend.models import (  # noqa: E402
    Job, Preference, WatchlistCompany, db,
)
from services.maintenance import refresh_freshness  # noqa: E402
from services.rescore import rescore_jobs  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--batch', type=int, default=200)
    parser.add_argument('--missing', action='store_true',
                        help='only jobs missing a field the current engine sets')
    parser.add_argument('--no-industry', action='store_true',
                        help='skip industry classification (faster)')
    args = parser.parse_args()

    with app.app_context():
        query = Job.query
        if args.missing:
            query = query.filter(or_(
                Job.final_score.is_(None),
                Job.application_recommendation.is_(None),
                Job.application_priority_score.is_(None),
                Job.golden_opportunity_score.is_(None),
                Job.industry.is_(None),
            ))
        query = query.order_by(Job.id)
        if args.limit:
            query = query.limit(args.limit)
        jobs = query.all()
        print(f'Rescoring {len(jobs)} jobs...')

        stats = rescore_jobs(
            db.session,
            {'Job': Job, 'WatchlistCompany': WatchlistCompany,
             'Preference': Preference},
            jobs,
            batch=args.batch,
            with_industry=not args.no_industry,
            progress=lambda i, total: print(f'  ...{i}/{total}'),
        )
        print(f'Done. {stats}')

        # Freshness is a function of *now*, so refresh it in the same pass.
        print('Refreshing freshness...', refresh_freshness(db.session))

        top = (
            Job.query.filter(Job.is_hidden.is_(False), Job.is_expired.is_(False))
            .order_by(Job.final_score.desc())
            .limit(10)
            .all()
        )
        print('\nTop 10 by final score:')
        for job in top:
            age = job.age_days()
            print(
                f'  {job.final_score:5.1f}  match={job.candidate_match_score:3d} '
                f'opp={job.opportunity_score:3d} q={job.job_quality_score:3d} '
                f'age={"?" if age is None else f"{age}d":>4s} '
                f'{(job.sponsorship_status or "unknown"):7s} '
                f'{job.title[:44]:44s} @ {job.company[:22]}'
            )


if __name__ == '__main__':
    main()
