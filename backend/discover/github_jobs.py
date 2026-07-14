"""
GitHub structured job feeds — SimplifyJobs listings.json (New-Grad + Internships).

These are the single largest free structured job source: tens of thousands of curated
new-grad and internship postings as clean JSON. The data lives on the `dev` branch under
.github/scripts/listings.json (the README is generated FROM this file — parsing the README
as HTML, as the old code did, always returned zero).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

FEEDS = [
    ("https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json", "new-grad"),
    ("https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json", "internship"),
]

ROLE_KEYWORDS = [
    "software", "engineer", "developer", "backend", "back end", "full stack", "full-stack",
    "frontend", "front end", "platform", "ai", "ml", "machine learning", "data engineer",
    "infrastructure", "devops", "sre", "product engineer", "swe", "sde", "llm", "agent",
    "web", "mobile", "ios", "android",
]

SENIOR_MARKERS = ["senior", " sr ", "sr.", "staff", "principal", "lead ", " lead", "director", "manager", "vp", "head of", "architect"]

INDIA_LOCS = ["bangalore", "bengaluru", "gurgaon", "gurugram", "hyderabad", "pune", "mumbai", "delhi", "noida", "chennai", "india"]


def _matches_location(locations, target_locations: list[str]) -> tuple[bool, bool]:
    """Return (matched, is_remote). locations may be a list or a string."""
    if isinstance(locations, list):
        loc_text = " ".join(str(x) for x in locations).lower()
    else:
        loc_text = str(locations or "").lower()
    is_remote = "remote" in loc_text or "anywhere" in loc_text
    if is_remote:
        return True, True
    for t in target_locations:
        if t.lower() in loc_text:
            return True, False
    if any(t in loc_text for t in INDIA_LOCS):
        return True, False
    return False, False


async def scrape_github(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50_000,
) -> list[JobListing]:
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India", "Hyderabad", "Pune"]

    jobs: list[JobListing] = []
    now = datetime.now(timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}

    async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
        for feed_url, kind in FEEDS:
            try:
                resp = await client.get(feed_url)
                resp.raise_for_status()
                listings = resp.json()
            except Exception as e:
                logger.warning(f"github feed {feed_url} failed: {e}")
                continue

            if not isinstance(listings, list):
                continue

            for item in listings:
                if not isinstance(item, dict):
                    continue
                if item.get("active") is False:
                    continue
                title = (item.get("title") or "").strip()
                company = (item.get("company_name") or item.get("company") or "").strip()
                if not title or not company:
                    continue

                title_lower = title.lower()
                if not any(kw in title_lower for kw in ROLE_KEYWORDS):
                    continue
                if any(s in title_lower for s in SENIOR_MARKERS):
                    continue

                locations = item.get("locations") or item.get("location") or []
                loc_match, is_remote = _matches_location(locations, target_locations)
                if not loc_match:
                    continue
                location = ", ".join(locations) if isinstance(locations, list) else str(locations)

                # Real posted date (epoch seconds).
                posted_date = None
                ts = item.get("date_posted") or item.get("date_updated")
                if ts:
                    try:
                        posted_date = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    except (ValueError, OSError, TypeError):
                        posted_date = None
                if posted_date:
                    age = (now - posted_date).total_seconds() / 86400
                    if age > max_age_days:
                        continue

                url = item.get("url") or item.get("application_link") or ""
                ext_id = item.get("id") or f"{company}-{title}"[:60]
                sponsorship = item.get("sponsorship", "")
                terms = item.get("terms") or []
                desc_bits = [x for x in [sponsorship, ", ".join(terms) if isinstance(terms, list) else str(terms)] if x]

                jobs.append(JobListing(
                    id=f"github-{kind}-{str(ext_id).lower().replace(' ', '-')[:50]}",
                    title=title,
                    company=company,
                    location=location or ("Remote" if is_remote else ""),
                    url=url,
                    source="github",
                    description=" | ".join(desc_bits),
                    posted_date=posted_date,
                    is_remote=is_remote,
                    employment_type="internship" if kind == "internship" else "full-time",
                    seniority="intern" if kind == "internship" else "new-grad",
                    company_size="unknown",
                ))

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique
