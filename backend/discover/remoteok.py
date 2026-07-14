import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

SOFTWARE_KEYWORDS = [
    "engineer", "developer", "full stack", "fullstack", "full-stack", "frontend", "front end",
    "backend", "back end", "ai", "ml", "data", "platform", "devops", "sre",
    "agent", "software", "mobile", "ios", "android", "web",
]
SENIOR_MARKERS = ["senior", "staff", "principal", "lead", "director", "head of", "manager", "vp", "architect", "sr.", "sr "]


async def scrape_remoteok(max_age_days: int = 4, target_locations: Optional[list[str]] = None) -> list[JobListing]:
    """RemoteOK public JSON API. Note: index [0] is metadata; real jobs start at [1].

    ToS requires a real User-Agent and attribution (link back) when displaying results.
    """
    jobs: list[JobListing] = []
    now = datetime.now(timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0; +https://github.com)"}

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get("https://remoteok.com/api")
            if resp.status_code != 200:
                logger.warning(f"remoteok returned {resp.status_code}")
                return jobs
            data = resp.json()
    except Exception as e:
        logger.warning(f"remoteok fetch failed: {e}")
        return jobs

    if not isinstance(data, list):
        return jobs

    for item in data[1:200]:  # [0] is the legal/metadata blob
        if not isinstance(item, dict):
            continue
        position = item.get("position", "") or item.get("title", "")
        company = item.get("company", "")
        url = item.get("url", "")
        tags = item.get("tags", []) or []
        location = item.get("location", "Remote") or "Remote"
        epoch = item.get("epoch", 0)

        if not position or not company:
            continue

        position_lower = position.lower()
        is_software = any(kw in position_lower for kw in SOFTWARE_KEYWORDS) or any(
            kw in tags for kw in ["python", "typescript", "react", "node", "rust", "go", "java", "backend", "frontend"]
        )
        if not is_software:
            continue
        # Exclude clearly senior roles; do not require an explicit junior keyword (that starves results).
        if any(s in position_lower for s in SENIOR_MARKERS):
            continue

        posted = None
        if epoch:
            try:
                posted = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            except (ValueError, OSError, TypeError):
                posted = None
        if posted:
            age = (now - posted).total_seconds() / 86400
            if age > max_age_days:
                continue

        jobs.append(JobListing(
            id=f"remoteok-{company.lower().replace(' ', '-')}-{position.lower().replace(' ', '-')[:40]}",
            title=position,
            company=company,
            location=location,
            url=url,
            source="remoteok",
            description=" | ".join(str(t) for t in tags[:10]),
            posted_date=posted,
            is_remote=True,
            employment_type="full-time",
            seniority="",
            company_size="startup",
        ))

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
