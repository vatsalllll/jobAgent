"""
Himalayas remote-jobs API client.
Public, unauthenticated, JSON. Endpoint:
    https://himalayas.app/jobs/api?limit=20&offset=0
Response: {"jobs": [...], "totalCount": N, "offset": ..., "limit": 20}.
Hard cap of 20 jobs per request, so we paginate with offset up to ~100 total.

Himalayas is a dedicated REMOTE board (every listing is remote-eligible), so we
mark is_remote=True and represent the location as "Remote (<region>)". The feed
covers all job categories, so the role filter narrows it to software/engineering.
Jobs are returned newest-first.
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

BASE_URL = "https://himalayas.app/jobs/api"
PAGE_LIMIT = 20  # API hard cap per request

DEFAULT_LOCATIONS = [
    "Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram",
    "India", "Hyderabad", "Pune",
]

# --- Balanced role filter (per source spec) --------------------------------
ROLE_INCLUDE = [
    "software", "engineer", "developer", "backend", "frontend",
    "full stack", "full-stack", "platform", "devops", "data engineer",
]
ROLE_INCLUDE_WB = ["ml", "ai", "sre", "sde"]
SENIOR_EXCLUDE = [
    "senior", "staff", "principal", "lead", "director",
    "manager", "vp", "head of", "architect",
]
SENIOR_EXCLUDE_WB = ["sr"]
# Himalayas exposes a `seniority` array — drop senior/management levels too.
SENIOR_LEVELS = {"senior", "staff", "principal", "lead", "director", "manager",
                 "executive", "head", "vp", "vice president", "chief"}

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


def _external_id(guid: str, company_slug: str, title: str) -> str:
    """Derive a stable external id from the job guid/slug."""
    if guid and "himalayas.app/" in guid:
        tail = guid.split("himalayas.app/", 1)[1].strip("/").replace("/", "-")
        if tail:
            return tail
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:50]
    return f"{company_slug}-{slug}".strip("-") or slug or "unknown"


def _parse_himalayas_job(
    j: dict,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
) -> Optional[JobListing]:
    title = j.get("title", "")
    if not _matches_role(title):
        return None

    seniority_vals = [str(s).lower() for s in (j.get("seniority") or [])]
    if any(any(sr in s for sr in SENIOR_LEVELS) for s in seniority_vals):
        return None

    # Every Himalayas job is remote; keep the region as a hint.
    restrictions = [r for r in (j.get("locationRestrictions") or []) if r]
    location = "Remote" if not restrictions else "Remote - " + ", ".join(restrictions)
    if not _matches_location(location, target_locations):
        return None

    # Real publication date — `pubDate` is a Unix epoch (seconds).
    posted_date = None
    raw_date = j.get("pubDate") or j.get("publishedDate")
    if raw_date is not None:
        try:
            posted_date = datetime.fromtimestamp(int(raw_date), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            posted_date = None
    if posted_date:
        age = (now - posted_date).total_seconds() / 86400
        if age > max_age_days:
            return None

    guid = j.get("guid") or j.get("applicationLink") or ""
    company_slug = j.get("companySlug") or ""
    ext_id = _external_id(guid, company_slug, title)

    company = j.get("companyName") or ""
    # Guard against the feed's occasional placeholder rows (literal "name").
    if company in ("name", ""):
        company = company_slug.replace("-", " ").title() if company_slug else "Unknown"

    url = j.get("applicationLink") or guid
    description = _strip_html(j.get("description", "")) or _strip_html(j.get("excerpt", ""))

    salary_min = j.get("minSalary")
    salary_max = j.get("maxSalary")
    currency = j.get("currency") or "INR"

    emp_raw = (j.get("employmentType") or "").lower()
    employment_type = "full-time"
    if "intern" in emp_raw or "intern" in title.lower():
        employment_type = "internship"
    elif "contract" in emp_raw or "freelance" in emp_raw:
        employment_type = "contract"
    elif "part" in emp_raw:
        employment_type = "part-time"

    seniority = ""
    if "intern" in title.lower():
        seniority = "intern"
    elif any("junior" in s or "entry" in s for s in seniority_vals):
        seniority = "junior"

    return JobListing(
        id=f"himalayas-{ext_id}",
        title=title,
        company=company,
        location=location,
        url=url,
        source="himalayas",
        description=description,
        salary_min=float(salary_min) if isinstance(salary_min, (int, float)) else None,
        salary_max=float(salary_max) if isinstance(salary_max, (int, float)) else None,
        salary_currency=currency,
        posted_date=posted_date,
        is_remote=True,
        employment_type=employment_type,
        seniority=seniority,
        company_size="",
    )


async def _fetch_offset(
    client: httpx.AsyncClient,
    offset: int,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
    semaphore: asyncio.Semaphore,
) -> list[JobListing]:
    out: list[JobListing] = []
    async with semaphore:
        try:
            resp = await client.get(BASE_URL, params={"limit": PAGE_LIMIT, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("himalayas: fetch failed (offset=%s): %s", offset, e)
            return out
    for j in data.get("jobs", []):
        try:
            job = _parse_himalayas_job(j, target_locations, max_age_days, now)
        except Exception:
            job = None
        if job is not None:
            out.append(job)
    return out


async def scrape_himalayas(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_total: int = 100,
    max_concurrent: int = 6,
) -> list[JobListing]:
    """Scrape the Himalayas remote-jobs API.

    Paginates offset in steps of 20 up to `max_total`, keeps software/engineering
    roles, and marks every listing is_remote=True. Never raises.
    """
    if target_locations is None:
        target_locations = DEFAULT_LOCATIONS

    now = datetime.now(timezone.utc)
    offsets = list(range(0, max(max_total, PAGE_LIMIT), PAGE_LIMIT))
    semaphore = asyncio.Semaphore(max_concurrent)
    all_jobs: list[JobListing] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
            tasks = [
                _fetch_offset(client, off, target_locations, max_age_days, now, semaphore)
                for off in offsets
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning("himalayas: scrape aborted: %s", e)
        return []

    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)

    seen: set[str] = set()
    unique: list[JobListing] = []
    for job in all_jobs:
        if job.id not in seen:
            seen.add(job.id)
            unique.append(job)
    return unique
