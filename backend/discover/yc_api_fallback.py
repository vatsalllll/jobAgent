"""
YC API fallback — when Playwright is disabled (e.g., on Render free tier),
use the public YC companies API to find hiring startups.
Returns synthetic job listings pointing to company careers pages.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

YC_API = "https://api.ycombinator.com/v0.1/companies"

ROLE_KEYWORDS = [
    "software engineer", "backend engineer", "full stack", "full-stack",
    "frontend engineer", "platform engineer", "ai engineer", "ml engineer",
    "machine learning", "data engineer", "infrastructure engineer",
    "devops", "site reliability", "product engineer", "application engineer",
    "engineering intern", "software intern", "swe intern", "software developer",
    "agent engineer", "llm engineer", "founding engineer",
]

JUNIOR_KEYWORDS = [
    "intern", "junior", "associate", "new grad", "entry level", "entry-level",
    "university", "campus", "graduate",
]


def _careers_url(website: str) -> str:
    """Guess the careers page URL from the company website."""
    base = website.rstrip("/")
    candidates = [
        f"{base}/jobs",
        f"{base}/careers",
        f"{base}/about#jobs",
        base,
    ]
    return candidates[0]


async def scrape_yc_api_fallback(
    max_age_days: int = 4,
    min_salary_inr: int = 50_000,
    target_locations: Optional[list[str]] = None,
    limit: int = 50,
) -> list[JobListing]:
    """
    Fetch YC companies with 'isHiring' badge via the public API.
    Returns synthetic JobListing objects with careers page URLs.
    """
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    jobs: list[JobListing] = []
    now = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                YC_API,
                params={"badges": "isHiring"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return jobs

    companies = data.get("companies", [])[:limit]

    for company in companies:
        name = (company.get("name") or "").strip()
        website = (company.get("website") or "").strip()
        locations = company.get("locations") or []
        regions = company.get("regions") or []
        batch = company.get("batch") or ""
        one_liner = company.get("oneLiner") or ""
        team_size = company.get("teamSize") or 0

        if not name or not website:
            continue

        # Check location match
        location_str = ", ".join(locations) if locations else "Remote"
        location_lower = location_str.lower()
        is_remote = "remote" in location_lower or "anywhere" in location_lower or "worldwide" in location_lower

        if not is_remote:
            all_locs = " ".join(locations + regions).lower()
            if not any(t.lower() in all_locs for t in target_locations + ["india", "remote", "worldwide", "anywhere"]):
                continue

        job_id = f"yc-api-{name.lower().replace(' ', '-')[:40]}"

        jobs.append(JobListing(
            id=job_id,
            title="Software Engineer (check careers page)",
            company=name,
            location=location_str or "Remote",
            url=_careers_url(website),
            source="yc",
            description=f"{one_liner} | Batch: {batch} | Team size: {team_size}",
            posted_date=now,
            is_remote=is_remote,
            employment_type="full-time",
            seniority="junior",
            company_size="startup",
        ))

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
