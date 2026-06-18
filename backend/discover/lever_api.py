import asyncio
from datetime import datetime, timezone

import httpx
from discover.models import JobListing

LEVER_BOARDS = [
    "spotify", "atlassian", "rippling", "figma-lever",
    "postman-lever", "twilio", "zapier", "canva",
    "plaid", "intercom", "monday", "grammarly",
    "benchling", "amplitude", "coinbase",
]

ROLE_KEYWORDS = [
    "software engineer", "backend", "full stack", "frontend",
    "platform", "ai engineer", "ml engineer", "machine learning",
    "data engineer", "infrastructure", "devops", "sre",
    "product engineer", "swe intern", "software intern",
    "llm", "agent", "software developer",
]

JUNIOR_KEYWORDS = ["intern", "junior", "associate", "new grad", "entry level", "university", "campus"]


async def scrape_lever_all(max_age_days=4, target_locations=None, max_concurrent=5):
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    all_jobs = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(company):
        async with semaphore:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"https://api.lever.co/v0/postings/{company}?mode=json"
                try:
                    resp = await client.get(url, timeout=30.0)
                    if resp.status_code != 200:
                        return []
                    data = resp.json()
                except Exception:
                    return []

                if not isinstance(data, list):
                    return []

                jobs = []
                for p in data:
                    title = p.get("text", "")
                    cats = p.get("categories", {})
                    commitment = cats.get("commitment", "")
                    location = cats.get("location", "")
                    title_l = title.lower()
                    loc_l = location.lower()

                    if not any(kw in title_l for kw in ROLE_KEYWORDS):
                        continue
                    if not any(kw in title_l for kw in JUNIOR_KEYWORDS) and "intern" not in commitment.lower():
                        continue
                    if not (any(t.lower() in loc_l for t in target_locations) or "remote" in loc_l or "india" in loc_l):
                        continue

                    jobs.append(JobListing(
                        id=f"lever-{company}-{title.lower().replace(' ', '-')[:40]}",
                        title=title,
                        company=company.replace("-lever", "").title(),
                        location=location,
                        url=p.get("hostedUrl", p.get("applyUrl", "")),
                        source="lever",
                        posted_date=datetime.now(timezone.utc),
                        is_remote="remote" in loc_l,
                        employment_type="internship" if "intern" in commitment.lower() else "full-time",
                        seniority="intern" if "intern" in title_l else "junior",
                        company_size="unknown",
                    ))
                return jobs

    tasks = [scrape_one(c) for c in LEVER_BOARDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)

    seen = set()
    unique = []
    for j in all_jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
