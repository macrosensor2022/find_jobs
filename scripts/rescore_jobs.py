"""Rescore all jobs with ProfileMatcher + metro opportunity ranking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app
from backend.models import db, Job
from scrapers.profile_matcher import ProfileMatcher
from scrapers.location_utils import canonicalize_location, in_target_states, load_cbsa_crosswalk
from scrapers.metro_opportunity import (
    lookup_opportunity_score, compute_competition_score, compute_rank_score,
    compute_metro_opportunity_scores,
)
from config.settings import Config
from datetime import datetime, timezone


def main():
    with app.app_context():
        try:
            load_cbsa_crosswalk()
        except FileNotFoundError as e:
            print(f'WARN: {e}')

        try:
            compute_metro_opportunity_scores(db.session)
        except AssertionError as e:
            print(f'LCA guardrail: {e}')
            print('Continuing rescore without metro opportunity refresh.')

        pm = ProfileMatcher()
        jobs = Job.query.filter(Job.is_hidden == False).all()
        updated = 0
        for job in jobs:
            score, _skills = pm.calculate_match_score({
                'title': job.title,
                'description': job.description or '',
                'location': job.location or '',
                'company': job.company or '',
            })
            job.match_score = score
            job.required_years = None
            job.exp_hard_drop = False
            # Re-evaluate on the job fields (calculate_match_score mutates a temp dict)
            exp = pm.evaluate_experience({
                'title': job.title,
                'description': job.description or '',
            })
            job.required_years = exp.get('required_years')
            job.exp_hard_drop = bool(exp.get('hard_drop'))
            if job.exp_hard_drop:
                job.match_score = 0
                job.is_hidden = True

            job.sponsorship_screen = pm.detect_sponsorship_screen(job.title, job.description)
            job.opt_field_related = score >= Config.OPT_FIELD_MATCH_MIN
            job.opt_fit_score = ProfileMatcher.compute_opt_fit_score(
                job.match_score, job.is_everify, job.sponsorship_screen, job.opt_field_related,
            )
            if job.date_posted:
                dp = job.date_posted
                if dp.tzinfo is None:
                    dp = dp.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - dp
                job.freshness_hours = max(0, int(delta.total_seconds() / 3600))

            loc = canonicalize_location(job.location or '')
            job.worksite_city = loc.get('city')
            job.worksite_state = loc.get('state')
            job.metro = loc.get('metro')
            job.metro_code = loc.get('metro_code')
            job.in_target_states = in_target_states(
                loc.get('state'), Config.TARGET_STATES, allow_remote=True,
            )
            if loc.get('state') in Config.EXCLUDED_STATES:
                job.is_hidden = True
                job.in_target_states = False
            elif loc.get('parse_ok') and loc.get('state') and not job.in_target_states:
                if loc.get('state') != 'REMOTE':
                    job.is_hidden = True

            job.location_opportunity_score = lookup_opportunity_score(db.session, job.metro_code)
            job.competition_score = compute_competition_score(
                {'freshness_hours': job.freshness_hours, 'source': job.source},
                source=job.source,
            )
            job.rank_score = compute_rank_score(
                job.match_score,
                job.employer_match_conf,
                job.location_opportunity_score,
                job.competition_score,
            )
            updated += 1
        db.session.commit()
        print(f'Rescored {updated} jobs with metro ranking')


if __name__ == '__main__':
    main()
