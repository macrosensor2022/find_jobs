import requests, json

r = requests.get('http://localhost:8080/api/jobs?per_page=15&sort_by=match_score', timeout=10)
data = r.json()
print(f"Total jobs in DB: {data['total']}")
print(f"Pages: {data['pages']}")
print()
print(f"{'Score':>5} | {'Title':<50} | {'Company':<25} | {'Source':<10} | {'Location'}")
print("-" * 140)
for j in data['jobs']:
    score = j.get('match_score', 0) or 0
    title = (j.get('title') or '')[:50]
    company = (j.get('company') or '')[:25]
    source = j.get('source', '')
    location = (j.get('location') or '')[:30]
    print(f"{score:>4}% | {title:<50} | {company:<25} | {source:<10} | {location}")
