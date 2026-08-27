"""Inspect stored jobs — a debugging aid, not part of the app.

    python scripts/inspect_jobs.py --title "AWS GDSP"
    python scripts/inspect_jobs.py --top 10
    python scripts/inspect_jobs.py --describe 135
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402
from backend.models import Job  # noqa: E402
from services.briefing import realistic_filters  # noqa: E402


def show(job):
    print(f'#{job.id} [{job.source}] {job.title}')
    print(f'   company        {job.company}')
    print(f'   location       {job.location}  (state={job.worksite_state}, '
          f'remote={job.remote_type})')
    print(f'   dedupe_key     {job.dedupe_key}')
    print(f'   duplicate_of   {job.duplicate_of_id}')
    print(f'   scores         final={job.final_score} match={job.candidate_match_score} '
          f'opp={job.opportunity_score} quality={job.job_quality_score}')
    print(f'   sponsorship    {job.sponsorship_status} — {job.sponsorship_reason}')
    if job.sponsorship_evidence:
        print(f'   evidence       "{job.sponsorship_evidence[:110]}"')
    print(f'   posted         {job.date_posted} (origin={job.date_posted_origin}) '
          f'bucket={job.freshness_bucket}')
    print(f'   apply          {job.application_url_status}: '
          f'{(job.application_url or "none")[:90]}')
    print(f'   blocked        location={job.location_blocked} role={job.role_blocked} '
          f'exp_hard_drop={job.exp_hard_drop} expired={job.is_expired}')
    print(f'   description    {len(job.description or "")} chars')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--title')
    parser.add_argument('--company')
    parser.add_argument('--top', type=int)
    parser.add_argument('--describe', type=int)
    parser.add_argument('--counts', action='store_true')
    args = parser.parse_args()

    with app.app_context():
        if args.describe:
            job = Job.query.get(args.describe)
            show(job)
            print('\n--- description ---')
            print((job.description or '(none)')[:3000])
            return

        if args.counts:
            total = Job.query.count()
            realistic = Job.query
            for condition in realistic_filters(Job):
                realistic = realistic.filter(condition)
            print(f'total jobs             {total}')
            print(f'hidden                 {Job.query.filter_by(is_hidden=True).count()}')
            print(f'expired                {Job.query.filter_by(is_expired=True).count()}')
            print(f'duplicates             '
                  f'{Job.query.filter(Job.duplicate_of_id.isnot(None)).count()}')
            print(f'location blocked       {Job.query.filter_by(location_blocked=True).count()}')
            print(f'role blocked           {Job.query.filter_by(role_blocked=True).count()}')
            print(f'sponsorship red        '
                  f'{Job.query.filter_by(sponsorship_status="red").count()}')
            print(f'exp hard drop          {Job.query.filter_by(exp_hard_drop=True).count()}')
            print(f'no description         '
                  f'{Job.query.filter(Job.description.is_(None)).count()}')
            print(f'no apply url           '
                  f'{Job.query.filter(Job.application_url.is_(None)).count()}')
            print(f'apply url verified     '
                  f'{Job.query.filter_by(application_url_status="verified").count()}')
            print(f'passes realistic gate  {realistic.count()}')
            by_source = {}
            for job in Job.query.all():
                by_source[job.source] = by_source.get(job.source, 0) + 1
            print('\nby source:')
            for source, count in sorted(by_source.items(), key=lambda kv: -kv[1]):
                print(f'  {source:16s} {count}')
            return

        query = Job.query
        if args.title:
            query = query.filter(Job.title.ilike(f'%{args.title}%'))
        if args.company:
            query = query.filter(Job.company.ilike(f'%{args.company}%'))
        query = query.order_by(Job.final_score.desc().nullslast())
        for job in query.limit(args.top or 20).all():
            show(job)
            print()


if __name__ == '__main__':
    main()
