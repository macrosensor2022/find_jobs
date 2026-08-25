"""Print metro opportunity breakdown + job state coverage."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app
from backend.models import db, Job
from scrapers.metro_opportunity import get_metro_breakdown

with app.app_context():
    print('=== Metro opportunity (verification) ===')
    for row in get_metro_breakdown(db.session, [
        'Hartford', 'Dallas-Fort Worth', 'Boston', 'Charlotte', 'Columbus',
    ]):
        print(
            f"  {row.get('metro_name')}: "
            f"density={row.get('sponsor_density')} "
            f"concentration={row.get('concentration_penalty')} "
            f"opportunity={row.get('location_opportunity_score')} "
            f"flag={row.get('flag')} filings={row.get('de_filing_count')}"
        )

    print('\n=== Jobs by worksite_state (visible) ===')
    rows = (
        db.session.query(Job.worksite_state, db.func.count(Job.id))
        .filter(Job.is_hidden == False)
        .group_by(Job.worksite_state)
        .all()
    )
    for st, n in sorted(rows, key=lambda x: -(x[1] or 0)):
        label = st if st else '(none)'
        print(f'  {label}: {n}')

    target = {'ME', 'TX', 'CT', 'NJ', 'MA', 'TN', 'NC', 'OH', 'MN', 'AZ', 'UT', 'CO'}
    present = {st for st, n in rows if st in target and n}
    print(f'\nTarget states with jobs: {sorted(present)} ({len(present)}/12)')
    print(f'DONE crawl check (>=3 new states): {len(present) >= 3}')
