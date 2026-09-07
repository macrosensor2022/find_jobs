"""Recompute stored ``dedupe_key`` values with the current normalization.

Why this exists
---------------
``dedupe_key`` is written once, when a job is first stored. When the
normalization in ``services/dedupe.py`` changes, existing rows keep the key the
old algorithm produced, and nothing refreshes them: ``rescore_job`` does
``job.dedupe_key = job.dedupe_key or build_dedupe_key(job)``, which only fills
NULLs.

The visible symptom was six genuinely different TikTok ML Engineer roles
(Visual Search, Basic Ranking, Recommendation, ...) all sharing one key,
because an older normalization discarded bracketed text. They are stored as
separate rows, but a seventh variant arriving today would be matched to
whichever one the lookup happened to return first and merged away.

What it does
------------
Recomputes every key deliberately — never ``existing or computed`` — then:

* writes keys that do **not** collide with any other job's new key;
* leaves colliding groups untouched and reports them.

It never merges, deletes, hides or otherwise modifies a job. The only column it
writes is ``dedupe_key``. Two rows sharing a key is a signal for a human to
look, not a licence to discard someone's job.

Usage
-----
    python scripts/repair_dedupe_keys.py              # dry run, reports only
    python scripts/repair_dedupe_keys.py --apply      # write the safe changes
    python scripts/repair_dedupe_keys.py --apply --include-collisions
"""

import argparse
import collections
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402  (initializes db + migrations)
from backend.models import Job, db  # noqa: E402
from services.dedupe import build_dedupe_key  # noqa: E402


def backup_database():
    """Copy the SQLite file next to itself before writing anything."""
    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    prefix = 'sqlite:///'
    if not uri.startswith(prefix):
        print(f'  ! not a SQLite database ({uri}); skipping backup')
        return None
    path = uri[len(prefix):]
    if not os.path.isabs(path):
        path = os.path.join(app.instance_path, path)
    if not os.path.exists(path):
        print(f'  ! database file not found at {path}; skipping backup')
        return None
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = f'{path}.{stamp}.bak'
    shutil.copy2(path, target)
    print(f'  backup: {target}')
    return target


def plan():
    """Work out what would change. Returns (updates, collisions, unchanged)."""
    jobs = Job.query.order_by(Job.id).all()

    # Deliberate recompute — never `job.dedupe_key or ...`.
    fresh = {}
    for job in jobs:
        fresh[job.id] = build_dedupe_key({
            'company': job.company,
            'title': job.title,
            'location': job.location,
            'job_url': job.job_url,
            'application_url': job.application_url,
        })

    by_key = collections.defaultdict(list)
    for job in jobs:
        if fresh[job.id]:
            by_key[fresh[job.id]].append(job)

    colliding_ids = {
        job.id for key, group in by_key.items() if len(group) > 1 for job in group
    }

    updates, collisions, unchanged = [], [], 0
    for job in jobs:
        new_key = fresh[job.id]
        if new_key is None or new_key == job.dedupe_key:
            unchanged += 1
            continue
        if job.id in colliding_ids:
            collisions.append((job, new_key))
        else:
            updates.append((job, new_key))

    collision_groups = {
        key: group for key, group in by_key.items() if len(group) > 1
    }
    return updates, collisions, unchanged, collision_groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='write the changes (default is a dry run)')
    parser.add_argument('--include-collisions', action='store_true',
                        help='also write keys for rows whose new key collides '
                             '(still never merges or deletes anything)')
    args = parser.parse_args()

    with app.app_context():
        updates, collisions, unchanged, groups = plan()

        print(f'Jobs examined            : {unchanged + len(updates) + len(collisions)}')
        print(f'Already correct          : {unchanged}')
        print(f'Stale, safe to rewrite   : {len(updates)}')
        print(f'Stale, key would collide : {len(collisions)}')
        print(f'Collision groups         : {len(groups)}')

        if groups:
            print('\nCollision groups (left alone unless --include-collisions):')
            for key, group in list(groups.items())[:10]:
                print(f'  {key}')
                for job in group:
                    print(f'      #{job.id} {job.title[:64]}')

        if updates:
            print('\nSample of safe rewrites:')
            for job, new_key in updates[:5]:
                print(f'  #{job.id} {job.title[:48]}')
                print(f'      old: {job.dedupe_key}')
                print(f'      new: {new_key}')

        if not args.apply:
            print('\nDry run — nothing written. Re-run with --apply to write.')
            return 0

        print('\nApplying...')
        backup_database()

        written = 0
        for job, new_key in updates:
            job.dedupe_key = new_key
            written += 1
        if args.include_collisions:
            for job, new_key in collisions:
                job.dedupe_key = new_key
                written += 1
        db.session.commit()

        print(f'  dedupe_key updated on {written} jobs')
        print('  no jobs merged, deleted or hidden')

        remaining_updates, remaining_collisions, _, _ = plan()
        print(f'  verification: {len(remaining_updates)} safe rewrites still '
              f'pending, {len(remaining_collisions)} collision rows left as-is')
        return 0


if __name__ == '__main__':
    sys.exit(main())
