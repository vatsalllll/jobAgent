import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from discover.models import JobListing


async def scrape_remoteok(max_age_days: int = 4, target_locations: Optional[list[str]] = None) -> list[JobListing]:
    """RemoteOK is a public JSON API for remote jobs."""
    if target_locations is None:
        target_locations = ["Remote", "Worldwide", "Anywhere"]

    jobs = []
    now = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://remoteok.com/api")
            if resp.status_code != 200:
                return jobs
            data = resp.json()
    except Exception:
        return jobs

        for item in data[1:50]:
            if not isinstance(item, dict):
                continue
            position = item.get("position", "")
            company = item.get("company", "")
            url = item.get("url", "")
            tags = item.get("tags", [])
            location = item.get("location", "Remote")
            epoch = item.get("epoch", 0)

            if not position or not company:
                continue

            position_lower = position.lower()
            is_software = any(kw in position_lower for kw in [
                "engineer", "developer", "full stack", "fullstack", "frontend",
                "backend", "ai", "ml", "data", "platform", "devops", "sre",
                "agent", "software", "mobile", "ios", "android", "web",
            ]) or any(kw in tags for kw in ["python", "typescript", "react", "node", "rust", "go"])

            if not is_software:
                continue

            posted = now
            if epoch:
                try:
                    posted = datetime.fromtimestamp(epoch, tz=timezone.utc)
                except Exception:
                    pass

            age = (now - posted).total_seconds() / 86400
            if age > 14:
                continue

            jobs.append(JobListing(
                id=f"remoteok-{company.lower().replace(' ', '-')}-{position.lower().replace(' ', '-')[:40]}",
                title=position,
                company=company,
                location=location or "Remote",
                url=url,
                source="remoteok",
                description=" | ".join(tags[:8]),
                posted_date=posted,
                is_remote=True,
                employment_type="full-time",
                seniority="mid",
                company_size="startup",
            ))

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
