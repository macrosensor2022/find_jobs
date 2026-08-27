"""Consolidate duplicate jobs already stored in the database.

Groups rows by their dedupe key, keeps the posting from the most authoritative
source (official ATS over aggregator), records every alternate source URL on the
survivor, and points the losers at it via duplicate_of_id. Nothing is deleted,
so a mistaken merge can always be inspected.

    python scripts/dedupe_existing.py --dry-run
    python scripts/dedupe_existing.py
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402
from backend.models import Job, db  # noqa: E402
from services.dedupe import build_dedupe_key, normalize_url, source_rank  # noqa: E402


def _survivor_sort_key(job):
    """Best posting first: trusted source, then richest data, then oldest row."""
    return (
        -source_rank(job.source),  # SOURCE_PRIORITY: higher is more authoritative
        0 if job.application_url_status == 'verified' else 1,
        0 if job.date_posted else 1,
        -len(job.description or ''),
        job.id,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    with app.app_context():
        stats = {'merged': 0, 'groups': 0, 'rebuilt': 0}

        # Pass 1: identity key (company + normalized title + location).
        # Pass 2: identical apply URL, which catches one posting listed under
        # several locations.
        for label, key_of in (
            ('identity', _identity_key),
            ('apply url', _url_key),
        ):
            groups = defaultdict(list)
            for job in Job.query.filter(Job.duplicate_of_id.is_(None)).all():
                if not job.dedupe_key:
                    rebuilt_key = build_dedupe_key(job)
                    if not args.dry_run:
                        job.dedupe_key = rebuilt_key
                    stats['rebuilt'] += 1
                key = key_of(job)
                if key:
                    groups[key].append(job)

            for members in groups.values():
                if len(members) < 2:
                    continue
                stats['groups'] += 1
                members.sort(key=_survivor_sort_key)
                keeper, losers = members[0], members[1:]

                alternates = json.loads(keeper.alt_source_urls or '[]')
                for loser in losers:
                    entry = {
                        'source': loser.source,
                        'url': loser.application_url or loser.job_url,
                        'location': loser.location,
                    }
                    if entry['url'] and entry not in alternates:
                        alternates.append(entry)
                    if not args.dry_run:
                        loser.duplicate_of_id = keeper.id
                        loser.is_hidden = True
                    stats['merged'] += 1

                if not args.dry_run:
                    keeper.alt_source_urls = json.dumps(alternates)

                print(f'[{label}] {keeper.source:14s} keeps #{keeper.id} '
                      f'"{keeper.title[:40]}" @ {(keeper.company or "?")[:20]}'
                      '  <- ' + ', '.join(f'{l.source}#{l.id}' for l in losers))

            if not args.dry_run:
                db.session.commit()

        print(f"\ngroups with duplicates: {stats['groups']}")
        print(f"rows marked as duplicates: {stats['merged']}")
        print(f"dedupe keys rebuilt: {stats['rebuilt']}")
        if args.dry_run:
            print('(dry run — nothing was written)')


def _identity_key(job):
    return job.dedupe_key or build_dedupe_key(job)


def _url_key(job):
    return normalize_url(job.application_url or job.job_url)


if __name__ == '__main__':
    main()
