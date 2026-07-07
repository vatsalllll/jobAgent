"""Hacker News "Who is Hiring" job scraper — completely free.

Uses the Algolia HN Search API (free, no key required) to find the latest
monthly hiring thread, then parses top-level comments for job listings.

HN threads: https://news.ycombinator.com/item?id={thread_id}
Algolia API: https://hn.algolia.com/api/v1/search_by_date
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

HN_API = "https://hn.algolia.com/api/v1"

# Common tech job title keywords to filter for
ROLE_KEYWORDS = [
    "software engineer", "backend", "frontend", "full stack", "full-stack",
    "devops", "sre", "platform", "infrastructure", "ai engineer", "ml engineer",
    "data engineer", "mobile engineer", "ios", "android", "security engineer",
    "engineering manager", "tech lead", "staff engineer", "principal engineer",
    "founding engineer",
]

SENIOR_KEYWORDS = [
    "senior", "staff", "principal", "lead", "director", "head of", "vp",
    "manager", "architect", "distinguished",
]

JUNIOR_KEYWORDS = [
    "intern", "junior", "new grad", "entry level", "entry-level", "associate",
    "university", "campus", "graduate",
]


def _extract_company_name(text: str) -> str:
    """Heuristic: first line or first capitalized words are often the company."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    first = lines[0]
    # Remove common prefixes
    first = re.sub(r"^\s*\*\s*", "", first)
    first = re.sub(r"^\s*-\s*", "", first)
    for sep in [" - ", " | ", " — ", "–"]:
        if sep in first:
            return first.split(sep)[0].strip()
    # Take first 2-3 words if they look like a name
    words = first.split()[:3]
    return " ".join(words)


def _extract_url(text: str) -> str:
    """Find first http URL in text."""
    match = re.search(r"https?://[^\s\)\"]+", text)
    if match:
        url = match.group(0)
        # Clean trailing punctuation
        url = url.rstrip(".,;:!?)")
        return url
    return ""


def _is_junior_role(title: str) -> bool:
    """Check if a role title looks entry-level / junior."""
    t = title.lower()
    return any(k in t for k in JUNIOR_KEYWORDS)


def _is_senior_role(title: str) -> bool:
    """Check if a role title looks senior (to skip)."""
    t = title.lower()
    return any(k in t for k in SENIOR_KEYWORDS)


def _extract_role_title(text: str) -> str:
    """Try to extract a role title from the first line or context."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    first = lines[0]
    # Look for patterns like "Company Name - Role Title" or "Company Name | Role"
    for sep in [" - ", " | ", " — ", "–"]:
        if sep in first:
            parts = first.split(sep)
            if len(parts) >= 2:
                return parts[1].strip()
    # Look for known role keywords in first 2 lines
    for line in lines[:3]:
        line_lower = line.lower()
        for kw in ROLE_KEYWORDS:
            if kw in line_lower:
                return line.strip()
    return ""


async def _find_latest_hiring_thread() -> Optional[int]:
    """Find the most recent 'Who is Hiring?' thread ID using Algolia API."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HN_API}/search_by_date",
                params={
                    "query": "Who is hiring",
                    "tags": "story",
                    "hitsPerPage": 5,
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            hits = data.get("hits", [])
            for hit in hits:
                title = hit.get("title", "").lower()
                if "who is hiring" in title:
                    return hit.get("objectID")
            return None
    except Exception as e:
        logger.warning(f"HN thread search failed: {e}")
        return None


async def _fetch_thread_comments(thread_id: int) -> list[dict]:
    """Fetch top-level comments from a thread."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HN_API}/items/{thread_id}",
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            children = data.get("children", [])
            return children
    except Exception as e:
        logger.warning(f"HN thread fetch failed for {thread_id}: {e}")
        return []


def _parse_comment(comment: dict) -> Optional[JobListing]:
    """Parse a single top-level comment into a JobListing if it looks like a job post."""
    text = comment.get("text", "")
    if not text or len(text) < 100:
        return None

    # Decode HTML entities (basic)
    text = text.replace("<p>", "\n").replace("</p>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    company = _extract_company_name(text)
    role = _extract_role_title(text)
    url = _extract_url(text)

    if not company or not role:
        return None

    role_lower = role.lower()

    # Filter for software/engineering roles
    if not any(kw in role_lower for kw in ROLE_KEYWORDS):
        return None

    # Skip senior roles
    if _is_senior_role(role):
        return None

    is_junior = _is_junior_role(role)
    is_remote = "remote" in text.lower()
    location = "Remote" if is_remote else ""

    job_id = f"hn-{company.lower().replace(' ', '-')}-{role_lower.replace(' ', '-')[:40]}"
    now = datetime.now(timezone.utc)

    return JobListing(
        id=job_id,
        title=role,
        company=company,
        location=location,
        url=url or f"https://news.ycombinator.com/item?id={comment.get('id', '')}",
        source="hackernews",
        description=text[:800],
        posted_date=now,
        is_remote=is_remote,
        employment_type="full-time",
        seniority="junior" if is_junior else "mid",
        company_size="startup",
    )


async def scrape_hackernews_jobs(
    max_age_days: int = 30,
    target_locations: Optional[list[str]] = None,
) -> list[JobListing]:
    """Scrape Hacker News 'Who is Hiring' thread for software engineering jobs."""
    if target_locations is None:
        target_locations = ["Remote"]

    thread_id = await _find_latest_hiring_thread()
    if not thread_id:
        logger.warning("No recent HN hiring thread found")
        return []

    logger.info(f"Found HN hiring thread: {thread_id}")
    comments = await _fetch_thread_comments(thread_id)

    jobs: list[JobListing] = []
    for comment in comments:
        job = _parse_comment(comment)
        if job:
            # Location filter
            loc_match = any(t.lower() in job.location.lower() for t in target_locations) or job.is_remote
            if loc_match or not job.location:
                jobs.append(job)

    # Deduplicate by company+title
    seen = set()
    unique = []
    for j in jobs:
        key = f"{j.company.lower()}|{j.title.lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    logger.info(f"HN scrape: found {len(unique)} unique jobs from {len(comments)} comments")
    return unique[:50]  # Cap at 50 to avoid overwhelming the pipeline
