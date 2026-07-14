"""
Workable public careers-widget API client.
Public, unauthenticated, JSON — no partnership needed.
Endpoint: https://apply.workable.com/api/v1/widget/accounts/{account}?details=true
Returns JSON with `name` (company) and `jobs[]` (title, shortcode, url, city/country,
telecommuting, published_on, description HTML).

Seed accounts below were each verified live (2026-07-14) to return >0 jobs.
Note: Workable rate-limits bursts (HTTP 429 + JS challenge), so concurrency is kept low.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

# Account slugs verified live to return >0 jobs via the widget API.
# apna (India), netguru & huggingface (remote-first) hire in India/remote;
# the rest are EU-based but verified live with open postings.
WORKABLE_ACCOUNTS = [
    "huggingface",
    "apna",
    "netguru",
    "blueground",
    "orfium",
    "skroutz",
    "learnworlds",
    "persado",
    "epignosis",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}

DEFAULT_LOCATIONS = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India", "Hyderabad", "Pune"]

ROLE_SUBSTRINGS = [
    "software", "engineer", "developer", "backend", "back end", "back-end",
    "frontend", "front end", "front-end", "full stack", "full-stack",
    "data engineer", "platform", "devops", "site reliability",
]
ROLE_WORDS = ["ml", "ai", "sde", "sre"]
SENIOR_SUBSTRINGS = [
    "senior", "staff", "principal", "lead", "director", "manager", "head of", "architect",
]
SENIOR_WORDS = ["sr", "vp"]

REMOTE_TOKENS = ["remote", "anywhere", "worldwide", "distributed"]
LOCATION_ALWAYS = ["remote", "anywhere", "worldwide", "india"]


def _role_ok(title: str) -> bool:
    t = (title or "").lower()
    if not t:
        return False
    for kw in SENIOR_SUBSTRINGS:
        if kw in t:
            return False
    for kw in SENIOR_WORDS:
        if re.search(r"\b" + kw + r"\b", t):
            return False
    for kw in ROLE_SUBSTRINGS:
        if kw in t:
            return True
    for kw in ROLE_WORDS:
        if re.search(r"\b" + kw + r"\b", t):
            return True
    return False


def _location_ok(location: str, targets: list[str]) -> bool:
    loc = (location or "").lower()
    if not loc:
        return False
    for t in targets:
        if t.lower() in loc:
            return True
    for t in LOCATION_ALWAYS:
        if t in loc:
            return True
    return False


def _is_remote(location: str) -> bool:
    loc = (location or "").lower()
    return any(t in loc for t in REMOTE_TOKENS)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean_html(text: str, limit: int = 6000) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _build_location(job: dict) -> tuple[str, bool]:
    """Return (location_string, is_remote) from a Workable job object."""
    telecommuting = bool(job.get("telecommuting"))
    parts = [job.get("city"), job.get("state"), job.get("country")]
    full = ", ".join(p for p in parts if p).strip(", ").strip()
    if telecommuting and "remote" not in full.lower():
        full = f"{full} (Remote)".strip() if full else "Remote"
    return full, (telecommuting or _is_remote(full))


async def _scrape_account(
    client: httpx.AsyncClient,
    account: str,
    target_locations: list[str],
    max_age_days: int,
) -> list[JobListing]:
    """Scrape one Workable account for matching jobs."""
    jobs: list[JobListing] = []
    try:
        resp = await client.get(
            f"https://apply.workable.com/api/v1/widget/accounts/{account}",
            params={"details": "true"},
        )
        resp.raise_for_status()
        if "json" not in resp.headers.get("content-type", ""):
            logger.warning("workable: %s returned non-JSON (likely rate-limited)", account)
            return jobs
        data = resp.json()
    except Exception as exc:
        logger.warning("workable: %s failed: %s", account, exc)
        return jobs

    company = data.get("name", account)
    now = datetime.now(timezone.utc)

    for job in data.get("jobs", []) or []:
        title = job.get("title", "")
        if not _role_ok(title):
            continue
        location, remote = _build_location(job)
        if not _location_ok(location, target_locations):
            continue

        posted = _parse_dt(job.get("published_on") or job.get("created_at"))
        if posted is not None and (now - posted).total_seconds() / 86400 > max_age_days:
            continue

        shortcode = job.get("shortcode", "")
        title_lower = title.lower()
        is_intern = "intern" in title_lower
        if is_intern:
            seniority = "intern"
        elif any(k in title_lower for k in ("junior", "associate", "graduate", "entry", "new grad")):
            seniority = "junior"
        else:
            seniority = ""

        jobs.append(JobListing(
            id=f"workable-{account}-{shortcode}",
            title=title,
            company=company,
            location=location,
            url=job.get("url") or job.get("shortlink") or job.get("application_url", ""),
            source="workable",
            description=_clean_html(job.get("description", "")),
            posted_date=posted,
            is_remote=remote,
            employment_type="internship" if is_intern else "full-time",
            seniority=seniority,
            company_size="startup",
        ))

    return jobs


async def scrape_workable(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_concurrent: int = 4,
) -> list[JobListing]:
    """Scrape all configured Workable accounts concurrently.

    min_salary_inr is accepted for a uniform signature but not used to filter.
    """
    if target_locations is None:
        target_locations = list(DEFAULT_LOCATIONS)

    all_jobs: list[JobListing] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(account: str) -> list[JobListing]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
                    return await _scrape_account(client, account, target_locations, max_age_days)
            except Exception as exc:
                logger.warning("workable: %s failed: %s", account, exc)
                return []

    results = await asyncio.gather(
        *[scrape_one(a) for a in WORKABLE_ACCOUNTS], return_exceptions=True
    )
    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)

    seen = set()
    unique: list[JobListing] = []
    for job in all_jobs:
        if job.id not in seen:
            seen.add(job.id)
            unique.append(job)
    return unique
