"""Indeed job scraper using RSS feeds — completely free, no API key needed.

Indeed provides RSS feeds for any search query:
  https://www.indeed.com/rss?q={query}&l={location}&fromage={days}

Parameters:
  q = search query (e.g., "software+engineer")
  l = location (e.g., "remote" or "India")
  fromage = max age in days (1, 3, 7, 14)

Note: Indeed RSS includes only basic fields (title, company, link, description, date).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

INDEED_RSS_BASE = "https://www.indeed.com/rss"
INDEED_RSS_INDIA = "https://www.indeed.co.in/rss"

ROLE_KEYWORDS = [
    "software engineer", "software developer", "backend", "frontend", "full stack",
    "full-stack", "devops", "sre", "platform engineer", "ai engineer", "ml engineer",
    "data engineer", "mobile engineer", "security engineer", "site reliability",
]

SENIOR_KEYWORDS = [
    "senior", "staff", "principal", "lead", "director", "head of", "vp",
    "manager", "architect", "distinguished",
]

JUNIOR_KEYWORDS = [
    "intern", "junior", "new grad", "entry level", "entry-level", "associate",
    "fresher", "trainee", "graduate",
]


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string to datetime."""
    if not date_str:
        return None
    try:
        # Common RSS date formats
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ]:
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # feedparser sometimes returns struct_time
        if hasattr(date_str, "tm_year"):
            return datetime(*date_str[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _extract_company_from_title(title: str) -> str:
    """Indeed RSS titles often look like: 'Role - Company' or 'Role at Company'."""
    # Pattern: "Software Engineer - Google" or "Software Engineer at Google"
    for sep in [" - ", " at ", " | "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                return parts[-1].strip()
    return ""


def _extract_role_from_title(title: str) -> str:
    """Extract role from Indeed title."""
    for sep in [" - ", " at ", " | "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                return parts[0].strip()
    return title.strip()


def _is_junior_role(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in JUNIOR_KEYWORDS)


def _is_senior_role(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in SENIOR_KEYWORDS)


async def _fetch_indeed_rss(query: str, location: str, fromage: int, india: bool = False) -> list[JobListing]:
    """Fetch a single Indeed RSS feed and parse jobs."""
    base = INDEED_RSS_INDIA if india else INDEED_RSS_BASE
    url = f"{base}?q={query.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage={fromage}"

    jobs: list[JobListing] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Indeed RSS returned {resp.status_code} for {url}")
                return []
            feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"Indeed RSS fetch failed: {e}")
        return []

    for entry in feed.entries:
        try:
            title = entry.get("title", "")
            if not title:
                continue

            role = _extract_role_from_title(title)
            company = _extract_company_from_title(title)
            role_lower = role.lower()

            # Filter for tech roles
            if not any(kw in role_lower for kw in ROLE_KEYWORDS):
                continue

            # Skip senior
            if _is_senior_role(role):
                continue

            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = _parse_date(entry.get("published", ""))

            is_remote = "remote" in (role_lower + " " + summary.lower())
            loc = "Remote" if is_remote else location

            job_id = f"indeed-{company.lower().replace(' ', '-')}-{role_lower.replace(' ', '-')[:40]}"

            jobs.append(JobListing(
                id=job_id,
                title=role,
                company=company or "Unknown",
                location=loc,
                url=link,
                source="indeed",
                description=summary[:800],
                posted_date=published or datetime.now(timezone.utc),
                is_remote=is_remote,
                employment_type="full-time",
                seniority="junior" if _is_junior_role(role) else "mid",
                company_size="unknown",
            ))
        except Exception:
            continue

    return jobs


async def scrape_indeed_jobs(
    max_age_days: int = 7,
    target_locations: Optional[list[str]] = None,
    queries: Optional[list[str]] = None,
) -> list[JobListing]:
    """Scrape Indeed RSS for software engineering jobs.

    Args:
        max_age_days: Maximum age of listings (maps to fromage: 1, 3, 7, 14)
        target_locations: List of locations to search
        queries: Search queries to run (defaults to common SWE queries)
    """
    if target_locations is None:
        target_locations = ["Remote", "India"]
    if queries is None:
        queries = ["software engineer", "backend engineer", "full stack engineer", "devops engineer"]

    # Map max_age_days to Indeed fromage values
    if max_age_days <= 1:
        fromage = 1
    elif max_age_days <= 3:
        fromage = 3
    elif max_age_days <= 7:
        fromage = 7
    else:
        fromage = 14

    all_jobs: list[JobListing] = []
    tasks = []

    for query in queries:
        for loc in target_locations:
            tasks.append(_fetch_indeed_rss(query, loc, fromage, india=(loc.lower() == "india")))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)
        else:
            logger.warning(f"Indeed scrape task failed: {result}")

    # Deduplicate
    seen = set()
    unique = []
    for j in all_jobs:
        key = f"{j.company.lower()}|{j.title.lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    logger.info(f"Indeed scrape: found {len(unique)} unique jobs")
    return unique[:50]
