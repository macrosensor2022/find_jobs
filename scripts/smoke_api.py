"""Smoke-test the live API end to end.

Hits every endpoint the dashboard depends on and prints real stored values so
regressions are obvious. Run against a local server:

    python run.py                 # in one terminal
    python scripts/smoke_api.py   # in another
"""

import argparse
import json
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8080'


def call(path, method='GET', payload=None, timeout=90):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b'{}')
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body or b'{}')
        except ValueError:
            return exc.code, {'raw': body[:200].decode(errors='replace')}


def show_briefing(limit):
    status, data = call(f'/api/briefing?limit={limit}')
    print(f'GET /api/briefing -> {status}')
    if status != 200:
        print('  ', data)
        return []
    counts = data['counts']
    for key in ('new_today', 'strong_matches', 'excellent_matches',
                'target_company_matches', 'sponsorship_positive',
                'posted_last_24h', 'followups_due', 'applyable_total'):
        print(f'   {key:24s} {counts.get(key)}')
    run = data.get('last_run')
    print('   last_run                 ',
          f"{run['trigger']}/{run['status']} accepted={run['jobs_accepted']}"
          if run else 'none recorded')

    print('\n  Top jobs:')
    for i, job in enumerate(data['top_jobs'], 1):
        print(f"  #{i} {job['final_score']:5.1f} match={job['candidate_match_score']:3d} "
              f"opp={job['opportunity_score']:3d} q={job['job_quality_score']:3d} "
              f"{job['sponsorship_status']:7s} {job['freshness_bucket']:8s} "
              f"tier={job['role_tier']} apply={job['can_apply']}")
        print(f"      {job['title'][:60]} @ {job['company'][:28]} | "
              f"{(job['location'] or 'Unknown')[:34]}")
        print(f"      why:  {', '.join(job['match_reasons'][:5]) or '-'}")
        print(f"      gaps: {', '.join(job['match_gaps'][:4]) or '-'}")
        print(f"      risk: {', '.join(job['match_risks'][:3]) or '-'}")
    return data['top_jobs']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--prepare', action='store_true',
                        help='also generate application prep for the top job')
    args = parser.parse_args()

    top = show_briefing(args.limit)

    print('\n--- other endpoints ---')
    checks = [
        ('/api/stats', lambda d: f"{d.get('total_jobs')} jobs"),
        ('/api/sources/metrics', lambda d: f"{len(d.get('sources', []))} sources"),
        ('/api/search-runs?limit=3', lambda d: f"{len(d.get('runs', []))} runs"),
        ('/api/applications', lambda d: f"{len(d.get('applications', []))} applications"),
        ('/api/followups', lambda d: f"{len(d.get('due', []))} due"),
        ('/api/watchlist', lambda d: f"{len(d.get('companies', []))} companies"),
        ('/api/notifications', lambda d: f"{d.get('unread_count')} unread"),
        ('/api/analytics/outcomes', lambda d: f"{d.get('total_applications')} tracked"),
        ('/api/external-search', lambda d: f"{len(d.get('links', []))} links"),
        ('/api/preferences', lambda d: f"{len(d)} preference keys"),
        ('/api/schedule', lambda d: f"next={d.get('next_run')}"),
        ('/api/jobs?per_page=1&realistic_only=true',
         lambda d: f"{d.get('total')} realistic jobs"),
    ]
    for path, describe in checks:
        status, data = call(path)
        try:
            summary = describe(data) if status == 200 else data
        except Exception as exc:
            summary = f'unexpected shape: {exc}'
        print(f'  {status}  {path:46s} {summary}')

    if args.prepare and top:
        job_id = top[0]['id']
        status, prep = call(f'/api/jobs/{job_id}/prepare', method='POST')
        print(f'\nPOST /api/jobs/{job_id}/prepare -> {status}')
        if status == 200:
            print('  resume:', prep['resume_recommendation'])
            print('  bullets:', len(prep['resume_bullets']))
            print('  summary:', (prep['professional_summary'] or '')[:130])
            sensitive = [q for q in prep['screening_questions'] if q['sensitive']]
            print(f"  questions: {len(prep['screening_questions'])} total, "
                  f"{len(sensitive)} reserved for my own review")
            print('  sponsorship:', prep['sponsorship']['status'],
                  '-', prep['sponsorship']['reason'])
            print('  cover letter chars:', len(prep['cover_letter'] or ''))
        else:
            print('  ', prep)


if __name__ == '__main__':
    main()
