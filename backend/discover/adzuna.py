"""
Adzuna Jobs API client.
Requires free API credentials (app_id + app_key) read from the environment:
    ADZUNA_APP_ID / ADZUNA_APP_KEY
If either is unset the module logs an info line and returns [] gracefully
(it never raises out of the entry function).

Endpoint:
    https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
        ?app_id={id}&app_key={key}&what=software%20engineer&results_per_page=50
We query India ("in") plus a global market ("us") and merge the results.
Response: {"results": [{"title","location":{"display_name"},"created",
           "redirect_url","description","salary_min","salary_max","id"}, ...]}.
"""

import asyncio
import html as _html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; JobAgent/1.0)"
HEADERS = {"User-Agent": USER_AGENT}

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
WHAT = "software engineer"
RESULTS_PER_PAGE = 50

# India + one global market, merged. Currency is per-market (Adzuna returns
# salaries in the market's local currency).
COUNTRIES = ["in", "us"]
CURRENCY_BY_COUNTRY = {
    "in": "INR", "us": "USD", "gb": "GBP", "au": "AUD", "ca": "CAD",
    "de": "EUR", "fr": "EUR", "nl": "EUR", "sg": "SGD", "za": "ZAR",
}

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


def _parse_adzuna_job(
    res: dict,
    country: str,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
) -> Optional[JobListing]:
    title = res.get("title", "")
    title = _html.unescape(_TAG_RE.sub("", title)).strip()
    if not _matches_role(title):
        return None

    location = (res.get("location") or {}).get("display_name", "") or ""
    if not _matches_location(location, target_locations):
        return None

    # Real posted date — `created` is ISO-8601 (e.g. "2026-07-10T09:12:00Z").
    posted_date = None
    created = res.get("created")
    if created:
        try:
            posted_date = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if posted_date.tzinfo is None:
                posted_date = posted_date.replace(tzinfo=timezone.utc)
        except ValueError:
            posted_date = None
    if posted_date:
        age = (now - posted_date).total_seconds() / 86400
        if age > max_age_days:
            return None

    ext_id = res.get("id") or res.get("adref") or res.get("redirect_url", "")
    if not ext_id:
        return None

    salary_min = res.get("salary_min")
    salary_max = res.get("salary_max")
    loc_lower = location.lower()

    contract_time = (res.get("contract_time") or "").lower()
    employment_type = "full-time"
    if "part_time" in contract_time:
        employment_type = "part-time"
    if "intern" in title.lower():
        employment_type = "internship"

    return JobListing(
        id=f"adzuna-{ext_id}",
        title=title,
        company=(res.get("company") or {}).get("display_name", "") or "Unknown",
        location=location or "Unknown",
        url=res.get("redirect_url", ""),
        source="adzuna",
        description=_strip_html(res.get("description", "")),
        salary_min=float(salary_min) if isinstance(salary_min, (int, float)) else None,
        salary_max=float(salary_max) if isinstance(salary_max, (int, float)) else None,
        salary_currency=CURRENCY_BY_COUNTRY.get(country, "INR"),
        posted_date=posted_date,
        is_remote="remote" in loc_lower,
        employment_type=employment_type,
        seniority="intern" if "intern" in title.lower() else "",
        company_size="",
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    country: str,
    page: int,
    app_id: str,
    app_key: str,
    target_locations: list[str],
    max_age_days: int,
    now: datetime,
    semaphore: asyncio.Semaphore,
) -> list[JobListing]:
    url = f"{BASE_URL}/{country}/search/{page}"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": WHAT,
        "results_per_page": RESULTS_PER_PAGE,
        "sort_by": "date",
        "max_days_old": max_age_days,
        "content-type": "application/json",
    }
    out: list[JobListing] = []
    async with semaphore:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("adzuna: fetch failed (country=%s page=%s): %s", country, page, e)
            return out
    for res in data.get("results", []):
        try:
            job = _parse_adzuna_job(res, country, target_locations, max_age_days, now)
        except Exception:
            job = None
        if job is not None:
            out.append(job)
    return out


async def scrape_adzuna(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_pages: int = 2,
    max_concurrent: int = 4,
) -> list[JobListing]:
    """Scrape the Adzuna Jobs API for India + a global market and merge.

    Reads ADZUNA_APP_ID / ADZUNA_APP_KEY from the environment. If either is
    missing it logs an info line and returns [] (no exception). Never raises.
    """
    if target_locations is None:
        target_locations = DEFAULT_LOCATIONS

    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logger.info(
            "adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set — skipping Adzuna source."
        )
        return []

    now = datetime.now(timezone.utc)
    semaphore = asyncio.Semaphore(max_concurrent)
    all_jobs: list[JobListing] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
            tasks = [
                _fetch_page(
                    client, country, page, app_id, app_key,
                    target_locations, max_age_days, now, semaphore,
                )
                for country in COUNTRIES
                for page in range(1, max_pages + 1)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning("adzuna: scrape aborted: %s", e)
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
