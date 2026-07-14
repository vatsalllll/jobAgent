"""
Recruitee public careers API client.
Public, unauthenticated, JSON — no partnership needed.
Endpoint: https://{company}.recruitee.com/api/offers/
Returns JSON `offers[]` with title, location, description (HTML), published_at,
careers_url, salary, remote, id.

Seed companies below were each verified live (2026-07-14) to return >0 offers.
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

# Recruitee subdomains verified live to return >0 offers via the public API.
RECRUITEE_COMPANIES = [
    "bunq",
    "greenchoice",
    "channable",
    "bettercollective",
    "vandebron",
    "effectory",
    "jobs",
    "nmbrs",
    "wmreplyjobs",
    "helloprint",
    "floryn",
    "sendcloud",
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


def _build_location(offer: dict) -> tuple[str, bool]:
    """Return (location_string, is_remote) from a Recruitee offer object."""
    remote = bool(offer.get("remote"))
    full = offer.get("location") or ", ".join(
        p for p in [offer.get("city"), offer.get("state_name"), offer.get("country")] if p
    )
    full = (full or "").strip(", ").strip()
    if remote and "remote" not in full.lower():
        full = f"{full} (Remote)".strip() if full else "Remote"
    return full, (remote or _is_remote(full))


async def _scrape_company(
    client: httpx.AsyncClient,
    company: str,
    target_locations: list[str],
    max_age_days: int,
) -> list[JobListing]:
    """Scrape one Recruitee company for matching offers."""
    jobs: list[JobListing] = []
    try:
        resp = await client.get(f"https://{company}.recruitee.com/api/offers/")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("recruitee: %s failed: %s", company, exc)
        return jobs

    now = datetime.now(timezone.utc)

    for offer in data.get("offers", []) or []:
        title = offer.get("title", "")
        if not _role_ok(title):
            continue
        location, remote = _build_location(offer)
        if not _location_ok(location, target_locations):
            continue

        posted = _parse_dt(offer.get("published_at") or offer.get("created_at"))
        if posted is not None and (now - posted).total_seconds() / 86400 > max_age_days:
            continue

        offer_id = str(offer.get("id", ""))
        title_lower = title.lower()
        emp_code = (offer.get("employment_type_code") or "").lower()
        is_intern = "intern" in title_lower or "intern" in emp_code
        if is_intern:
            seniority = "intern"
        elif any(k in title_lower for k in ("junior", "associate", "graduate", "entry", "new grad")):
            seniority = "junior"
        else:
            seniority = ""

        description = _clean_html(offer.get("description", "")) or _clean_html(offer.get("requirements", ""))

        salary = offer.get("salary") or {}
        salary_min = salary.get("min")
        salary_max = salary.get("max")
        currency = salary.get("currency") or "INR"

        jobs.append(JobListing(
            id=f"recruitee-{offer_id}",
            title=title,
            company=offer.get("company_name") or company,
            location=location,
            url=offer.get("careers_url") or offer.get("careers_apply_url", ""),
            source="recruitee",
            description=description,
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            salary_currency=currency,
            posted_date=posted,
            is_remote=remote,
            employment_type="internship" if is_intern else "full-time",
            seniority=seniority,
            company_size="mid",
        ))

    return jobs


async def scrape_recruitee(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_concurrent: int = 8,
) -> list[JobListing]:
    """Scrape all configured Recruitee companies concurrently.

    min_salary_inr is accepted for a uniform signature but not used to filter.
    """
    if target_locations is None:
        target_locations = list(DEFAULT_LOCATIONS)

    all_jobs: list[JobListing] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(company: str) -> list[JobListing]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
                    return await _scrape_company(client, company, target_locations, max_age_days)
            except Exception as exc:
                logger.warning("recruitee: %s failed: %s", company, exc)
                return []

    results = await asyncio.gather(
        *[scrape_one(c) for c in RECRUITEE_COMPANIES], return_exceptions=True
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
