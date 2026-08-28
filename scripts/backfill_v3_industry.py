#!/usr/bin/env python
"""Backfill V3 industry classification + golden score on existing jobs.

Runs the same enrichment services used at scrape time so stored jobs reflect
industry/opportunity/golden without re-scraping. Contact discovery is left to
the scrape path (a contact needs a legitimate source hint, which only arrives
from a source), so this backfills industry + opportunity + golden only.

Safe to re-run (idempotent).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from backend.app import app, db
    from backend.models import Job
    from services.industry import classify_industry
    from services.golden import golden_opportunity_score
    from services.industry import industry_opportunity
    from datetime import datetime, timezone

    with app.app_context():
        jobs = Job.query.all()
        updated = 0
        for job in jobs:
            ind = classify_industry(
                title=job.title, description=job.description,
                company=job.company, source=job.source,
            )
            job.industry = ind['industry']
            job.industry_label = ind['label']
            job.under_the_radar = ind['under_the_radar']
            job.industry_evidence = json.dumps(ind['evidence'])

            # Industry-opportunity snapshot for this industry.
            if job.industry and job.industry != 'UNKNOWN':
                opp = industry_opportunity(db, Job, job.industry)
                job.industry_opportunity = opp['opportunity']
                job.industry_opportunity_score = opp['opportunity_score']

            # Golden composite with the enriched industry signal.
            fresh = (job.freshness_bucket or 'unknown')
            freshness_score = {'hot': 100.0, 'fresh': 85.0, 'recent': 65.0,
                               'aging': 45.0, 'old': 25.0, 'stale': 10.0,
                               'unknown': 50.0}.get(fresh, 50.0)
            result = golden_opportunity_score(
                match_score=job.candidate_match_score or 0,
                freshness_score=freshness_score,
                auth_status=job.sponsorship_status or 'unknown',
                quality_score=job.job_quality_score or 0,
                effort_estimate=job.application_effort_estimate,
                industry_opp_score=job.industry_opportunity_score,
                contact_relevance_score=None,
                competition_signal=job.competition_signal,
            )
            job.golden_opportunity_score = result['score']
            updated += 1
        db.session.commit()
        print(f'Backfilled industry + golden for {updated} jobs.')


if __name__ == '__main__':
    main()