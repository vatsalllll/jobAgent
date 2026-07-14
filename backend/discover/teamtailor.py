"""
Teamtailor public JSON Feed client.
Public, unauthenticated — no partnership needed. (Do NOT use api.teamtailor.com — paid.)
Endpoint: https://{company}.teamtailor.com/jobs.json  (JSON Feed 1.x)
Items carry title, url, date_published, content_html and a schema.org `_jobposting`
object whose `jobLocation[].address` holds the location.

Seed companies below were each verified live (2026-07-14) to return >0 feed items.
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

# Teamtailor subdomains verified live to return >0 items via the JSON feed.
TEAMTAILOR_COMPANIES = [
    "doktor",
    "instabee",
    "schibsted",
    "polestar",
    "career",
    "telavox",
    "tibber",
    "brite",
    "quinyx",
    "anyfin",
    "hedvig",
    "storytel",
    "bannerflow",
    "hemnet",
    "detectify",
    "lifesum",
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

# ISO 3166-1 alpha-2 -> country name, so the location filter (e.g. "india") works
# against schema.org addressCountry codes.
COUNTRY_CODES = {
    "IN": "India", "US": "United States", "GB": "United Kingdom", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "FI": "Finland", "DE": "Germany",
    "NL": "Netherlands", "FR": "France", "ES": "Spain", "PL": "Poland",
    "IE": "Ireland", "PT": "Portugal", "IT": "Italy", "CH": "Switzerland",
    "AT": "Austria", "BE": "Belgium", "CA": "Canada", "AU": "Australia",
    "SG": "Singapore", "AE": "United Arab Emirates", "LT": "Lithuania",
    "EE": "Estonia", "LV": "Latvia", "CZ": "Czechia", "RO": "Romania",
    "UA": "Ukraine", "BR": "Brazil", "MX": "Mexico", "JP": "Japan",
}


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


def _expand_country(value: str) -> str:
    if not value:
        return ""
    v = value.strip()
    if len(v) == 2 and v.upper() in COUNTRY_CODES:
        return COUNTRY_CODES[v.upper()]
    return v


def _build_location(item: dict, title: str, description: str) -> tuple[str, bool]:
    """Return (location_string, is_remote) for a Teamtailor feed item."""
    jobposting = item.get("_jobposting") or {}
    places = jobposting.get("jobLocation")
    if isinstance(places, dict):
        places = [places]
    parts: list[str] = []
    for place in places or []:
        addr = (place or {}).get("address", {}) or {}
        loc_bits = [
            addr.get("addressLocality"),
            addr.get("addressRegion"),
            _expand_country(addr.get("addressCountry", "")),
        ]
        piece = ", ".join(b for b in loc_bits if b).strip(", ").strip()
        if piece:
            parts.append(piece)
    full = " / ".join(dict.fromkeys(parts))  # de-dupe, preserve order

    # Detect remote from location type / title / body.
    loc_type = str(jobposting.get("jobLocationType", "")).lower()
    hint = " ".join([title.lower(), description[:400].lower()])
    remote = (
        "telecommute" in loc_type
        or _is_remote(full)
        or "remote" in hint
        or "work from home" in hint
    )
    if remote and "remote" not in full.lower():
        full = f"{full} (Remote)".strip() if full else "Remote"
    return full, remote


async def _scrape_company(
    client: httpx.AsyncClient,
    company: str,
    target_locations: list[str],
    max_age_days: int,
) -> list[JobListing]:
    """Scrape one Teamtailor company's JSON feed for matching jobs."""
    jobs: list[JobListing] = []
    try:
        resp = await client.get(f"https://{company}.teamtailor.com/jobs.json")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("teamtailor: %s failed: %s", company, exc)
        return jobs

    company_name = (data.get("title") or company).strip()
    now = datetime.now(timezone.utc)

    for item in data.get("items", []) or []:
        title = item.get("title", "")
        if not _role_ok(title):
            continue
        description = _clean_html(item.get("content_html", ""))
        location, remote = _build_location(item, title, description)
        if not _location_ok(location, target_locations):
            continue

        posted = _parse_dt(item.get("date_published"))
        if posted is not None and (now - posted).total_seconds() / 86400 > max_age_days:
            continue

        item_id = str(item.get("id", ""))
        title_lower = title.lower()
        is_intern = "intern" in title_lower
        if is_intern:
            seniority = "intern"
        elif any(k in title_lower for k in ("junior", "associate", "graduate", "entry", "new grad")):
            seniority = "junior"
        else:
            seniority = ""

        jobs.append(JobListing(
            id=f"teamtailor-{item_id}",
            title=title,
            company=company_name,
            location=location,
            url=item.get("url", ""),
            source="teamtailor",
            description=description,
            posted_date=posted,
            is_remote=remote,
            employment_type="internship" if is_intern else "full-time",
            seniority=seniority,
            company_size="mid",
        ))

    return jobs


async def scrape_teamtailor(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_concurrent: int = 8,
) -> list[JobListing]:
    """Scrape all configured Teamtailor companies concurrently.

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
                logger.warning("teamtailor: %s failed: %s", company, exc)
                return []

    results = await asyncio.gather(
        *[scrape_one(c) for c in TEAMTAILOR_COMPANIES], return_exceptions=True
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
