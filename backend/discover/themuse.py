"""
The Muse public Jobs API client.
Public, unauthenticated (500 req/hr, no key), JSON.
Endpoint: https://www.themuse.com/api/public/jobs?page={n}&category=Software%20Engineering

The generic feed is NOT sorted by date and skews toward older postings, so we
scope each request with the documented `location` param to the India metros +
remote pool we care about, paginate a few pages per location, then apply the
role / location / freshness filters client-side.
"""

import asyncio
import html as _html
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; JobAgent/1.0)"
HEADERS = {"User-Agent": USER_AGENT}

BASE_URL = "https://www.themuse.com/api/public/jobs"
CATEGORY = "Software Engineering"  # broad Muse category (~100k engineering roles)

DEFAULT_LOCATIONS = [
    "Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram",
    "India", "Hyderabad", "Pune",
]

# Map our target-location tokens -> canonical Muse `location` query values
# (Muse only filters on canonical "City, Country" / "Flexible / Remote" strings).
MUSE_LOCATION_MAP = {
    "remote": "Flexible / Remote",
    "anywhere": "Flexible / Remote",
    "worldwide": "Flexible / Remote",
    "india": "Bengaluru, India",
    "bangalore": "Bengaluru, India",
    "bengaluru": "Bengaluru, India",
    "gurgaon": "Gurgaon, India",
    "gurugram": "Gurgaon, India",
    "hyderabad": "Hyderabad, India",
    "pune": "Pune, India",
    "delhi": "Delhi, India",
    "mumbai": "Mumbai, India",
    "chennai": "Chennai, India",
    "noida": "Noida, India",
}

# --- Balanced role filter (per source spec) --------------------------------
ROLE_INCLUDE = [
    "software", "engineer", "developer", "backend", "frontend",
    "full stack", "full-stack", "platform", "devops", "data engineer",
]
ROLE_INCLUDE_WB = ["ml", "ai", "sre", "sde"]  # matched on word boundaries
SENIOR_EXCLUDE = [
    "senior", "staff", "principal", "lead", "director",
    "manager", "vp", "head of", "architect",
]
SENIOR_EXCLUDE_WB = ["sr"]  # catches "Sr." / " Sr " without matching e.g. "disrupt"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _matches_role(title: str) -> bool:
    t = (title or "").lower()
    if any(kw in t for kw in SENIOR_EXCLUDE):
        return False
    if any(re.search(rf"\b{kw}\b", t) for kw in SENIOR_EXCLUDE_WB):
        return False
    if any(kw in t for kw in ROLE_INCLUDE):
        return True
    return any(re.search(rf"\b{kw}\b", t) for kw in ROLE_INCLUDE_WB)


def _matches_location(location: str, targets: list[str]) -> bool:
    loc = (location or "").lower()
    if any((t or "").lower() in loc for t in targets):
        return True
    return any(x in loc for x in ("remote", "anywhere", "worldwide", "india"))


def _strip_html(raw: str, cap: int = 5000) -> str:
    if not raw:
        return ""
    text = _html.unescape(_TAG_RE.sub(" ", raw))
    return _WS_RE.sub(" ", text).strip()[:cap]


def _query_locations(target_locations: list[str]) -> list[str]:
    """Build the set of canonical Muse `location` values to query."""
    out: list[str] = []
    for t in target_locations:
        mapped = MUSE_LOCATION_MAP.get((t or "").lower().strip())
        if mapped and mapped not in out:
            out.append(mapped)
    if "Flexible / Remote" not in out:
        out.append("Flexible / Remote")  # always include the global-remote pool
    return out


def _parse_muse_job(
    res: dict,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
) -> Optional[JobListing]:
    title = res.get("name", "")
    if not _matches_role(title):
        return None

    # Extra precision: Muse exposes a `levels` array — drop senior/management.
    levels = res.get("levels") or []
    level_names = " ".join((lv.get("short_name") or lv.get("name") or "") for lv in levels).lower()
    if any(x in level_names for x in ("senior", "management")):
        return None

    location_names = [loc.get("name", "") for loc in (res.get("locations") or [])]
    location = ", ".join(filter(None, location_names)) or "Flexible / Remote"
    if not _matches_location(location, target_locations):
        return None

    # Real publication date (e.g. "2026-06-26T18:34:36Z").
    posted_date = None
    pub = res.get("publication_date")
    if pub:
        try:
            posted_date = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            posted_date = None
    if posted_date:
        age = (now - posted_date).total_seconds() / 86400
        if age > max_age_days:
            return None

    job_id_ext = res.get("id")
    if job_id_ext is None:
        return None
    landing = (res.get("refs") or {}).get("landing_page", "")
    company = (res.get("company") or {}).get("name", "") or "Unknown"
    loc_lower = location.lower()
    title_lower = title.lower()

    seniority = ""
    if "intern" in title_lower or "internship" in level_names:
        seniority = "intern"
    elif "entry" in level_names or "junior" in level_names:
        seniority = "junior"

    return JobListing(
        id=f"themuse-{job_id_ext}",
        title=title,
        company=company,
        location=location,
        url=landing,
        source="themuse",
        description=_strip_html(res.get("contents", "")),
        posted_date=posted_date,
        is_remote=("remote" in loc_lower or "flexible" in loc_lower),
        employment_type="internship" if "intern" in title_lower else "full-time",
        seniority=seniority,
        company_size="",
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    location: str,
    page: int,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
    semaphore: asyncio.Semaphore,
) -> list[JobListing]:
    params = {"page": page, "category": CATEGORY, "location": location}
    out: list[JobListing] = []
    async with semaphore:
        try:
            resp = await client.get(BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("themuse: fetch failed (location=%s page=%s): %s", location, page, e)
            return out
    for res in data.get("results", []):
        try:
            job = _parse_muse_job(res, target_locations, max_age_days, now)
        except Exception:
            job = None
        if job is not None:
            out.append(job)
    return out


async def scrape_themuse(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_pages: int = 5,
    max_concurrent: int = 8,
) -> list[JobListing]:
    """Scrape The Muse public Jobs API (Software Engineering category).

    Returns fresh software/engineering roles for the target (India + remote)
    locations. Never raises; on error returns whatever was collected.
    """
    if target_locations is None:
        target_locations = DEFAULT_LOCATIONS

    now = datetime.now(timezone.utc)
    query_locations = _query_locations(target_locations)
    semaphore = asyncio.Semaphore(max_concurrent)
    all_jobs: list[JobListing] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
            tasks = [
                _fetch_page(client, loc, page, target_locations, max_age_days, now, semaphore)
                for loc in query_locations
                for page in range(1, max_pages + 1)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning("themuse: scrape aborted: %s", e)
        return []

    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)

    # Deduplicate by stable id.
    seen: set[str] = set()
    unique: list[JobListing] = []
    for job in all_jobs:
        if job.id not in seen:
            seen.add(job.id)
            unique.append(job)
    return unique
