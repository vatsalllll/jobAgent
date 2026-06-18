import asyncio
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from discover.models import JobListing

GITHUB_WHOISHIRING = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"


ROLE_KEYWORDS = [
    "software engineer", "backend", "full stack", "full-stack", "frontend",
    "platform", "ai engineer", "ml engineer", "machine learning", "data engineer",
    "infrastructure", "devops", "sre", "product engineer", "swe intern",
    "software intern", "llm", "agent",
]


async def scrape_github() -> list[JobListing]:
    jobs = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(GITHUB_WHOISHIRING)
            resp.raise_for_status()
        except Exception:
            return jobs

        content = resp.text
        soup = BeautifulSoup(content, "html.parser")

        rows = soup.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            try:
                company = cols[0].get_text(strip=True)
                title = cols[1].get_text(strip=True)
                location = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                title_link = cols[1].find("a")
                url = title_link.get("href", "") if title_link else ""

                if not title or not company:
                    continue

                title_lower = title.lower()
                location_lower = location.lower()

                if not any(kw in title_lower for kw in ROLE_KEYWORDS):
                    continue

                is_junior = any(kw in title_lower for kw in ["intern", "junior", "new grad", "entry"])
                if not is_junior:
                    continue

                is_remote_or_india = "remote" in location_lower or "india" in location_lower or location_lower in ["remote", "anywhere"]

                if not is_remote_or_india:
                    loc_targets = ["bangalore", "bengaluru", "gurgaon", "gurugram", "hyderabad", "pune", "mumbai", "delhi", "india"]
                    if not any(t in location_lower for t in loc_targets):
                        continue

                job_id = f"gh-jobs-{company.lower().replace(' ', '-')}-{title.lower().replace(' ', '-')[:30]}"

                jobs.append(JobListing(
                    id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    source="github",
                    posted_date=now,
                    is_remote="remote" in location_lower,
                    employment_type="internship" if "intern" in title_lower else "full-time",
                    seniority="intern" if "intern" in title_lower else "junior",
                    company_size="unknown",
                ))
            except Exception:
                continue

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
