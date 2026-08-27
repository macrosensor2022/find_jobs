"""Final ranking: combines candidate match, opportunity and quality."""

from datetime import datetime, timezone

from config.settings import Config
from services.matching import evaluate_job
from services.opportunity import evaluate_opportunity
from services.quality import evaluate_quality


def final_score(match_score, opportunity_score, quality_score,
                match_weight=None, opportunity_weight=None):
    """FINAL = w1*match + w2*opportunity, scaled down by poor quality.

    Quality is a multiplier rather than an addend so that an untrustworthy
    listing can never outrank a verified one on keyword score alone.
    """
    match_weight = (
        Config.CANDIDATE_MATCH_WEIGHT if match_weight is None else match_weight
    )
    opportunity_weight = (
        Config.OPPORTUNITY_WEIGHT if opportunity_weight is None else opportunity_weight
    )
    total_weight = match_weight + opportunity_weight
    if total_weight <= 0:
        match_weight, opportunity_weight, total_weight = 0.7, 0.3, 1.0

    blended = (
        (match_score or 0) * match_weight + (opportunity_score or 0) * opportunity_weight
    ) / total_weight

    # 100 quality -> x1.0, 40 quality -> x0.82, 0 quality -> x0.70
    multiplier = 0.70 + 0.30 * (max(0, min(100, quality_score or 0)) / 100.0)
    return round(max(0.0, min(100.0, blended * multiplier)), 2)


def score_job(job, profile_skills=None, watchlist=None, weights=None,
              location_prefs=None, opportunity_weights=None, now=None):
    """Run the full scoring pipeline for one job and return a flat result."""
    match = evaluate_job(job, profile_skills=profile_skills, weights=weights,
                         location_prefs=location_prefs)
    opportunity = evaluate_opportunity(job, match_result=match, watchlist=watchlist,
                                       weights=opportunity_weights)
    quality = evaluate_quality(job)
    final = final_score(match['score'], opportunity['score'], quality['score'])

    return {
        'candidate_match_score': match['score'],
        'opportunity_score': opportunity['score'],
        'job_quality_score': quality['score'],
        'final_score': final,
        'eligible': match['eligible'] and quality['score'] >= Config.MIN_QUALITY_FOR_RANKING,
        'disqualifiers': match['disqualifiers'],
        'match': match,
        'opportunity': opportunity,
        'quality': quality,
        'freshness': opportunity['freshness'],
        'scored_at': (now or datetime.now(timezone.utc)),
    }


def apply_to_model(job_model, result):
    """Persist a scoring result onto a Job model instance."""
    import json

    match = result['match']
    job_model.candidate_match_score = result['candidate_match_score']
    job_model.opportunity_score = result['opportunity_score']
    job_model.job_quality_score = result['job_quality_score']
    job_model.final_score = result['final_score']
    job_model.match_score = result['candidate_match_score']
    job_model.match_breakdown = json.dumps(match['breakdown'])
    job_model.match_reasons = json.dumps(match['reasons'][:12])
    job_model.match_gaps = json.dumps(match['gaps'][:10])
    job_model.match_risks = json.dumps(
        (match['risks'] + result['quality']['flags'])[:12]
    )
    job_model.opportunity_breakdown = json.dumps(result['opportunity']['breakdown'])
    job_model.quality_flags = json.dumps(result['quality']['flags'])

    auth = match['authorization']
    job_model.sponsorship_status = auth['status']
    job_model.sponsorship_evidence = auth['evidence']
    job_model.sponsorship_evidence_source = auth['evidence_source']
    job_model.sponsorship_reason = auth['reason']
    job_model.sponsorship_screen = auth['status'] == 'red'

    role = match['role']
    job_model.role_family = role['family']
    job_model.role_tier = role['tier']
    job_model.seniority_level = role['seniority']
    job_model.remote_type = match['location']['remote_type']

    exp = match['experience']
    job_model.required_years = exp['required_years']
    job_model.exp_hard_drop = exp['hard_drop']

    freshness = result['freshness']
    job_model.freshness_bucket = freshness['bucket']
    job_model.freshness_hours = freshness['hours']
    job_model.scored_at = result['scored_at']

    # Flags that let the "only realistic applications" filter run in SQL
    # instead of loading and re-scoring every row.
    job_model.location_blocked = match['location']['score'] <= Config.LOCATION_BLOCK_MAX
    job_model.role_blocked = match['role']['score'] < Config.ROLE_BLOCK_MIN
    return job_model
