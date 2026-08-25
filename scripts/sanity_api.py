import requests, json

BASE = "http://127.0.0.1:8080"

print("PROFILE:")
print(json.dumps(requests.get(f"{BASE}/api/profile", timeout=10).json(), indent=2))

print("\nSTATS:")
print(json.dumps(requests.get(f"{BASE}/api/stats", timeout=10).json(), indent=2))

r = requests.get(f"{BASE}/api/jobs", params={
    "per_page": 5, "sort_by": "match_score", "date_filter": "week"
}, timeout=10)
d = r.json()
print(f"\nWEEK_JOBS total={d['total']}")
for j in d["jobs"][:5]:
    title = (j.get("title") or "")[:45]
    print(f"  {j.get('match_score')}% | {title} @ {j.get('company')}")

for path in ["/", "/static/css/style.css", "/static/js/app.js", "/api/config/keywords", "/api/config/locations"]:
    rr = requests.get(f"{BASE}{path}", timeout=10)
    print(f"{path}: {rr.status_code}")
