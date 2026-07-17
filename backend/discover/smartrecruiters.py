"""
SmartRecruiters public Posting API client.
Public, unauthenticated, JSON — no partnership needed.
List:   https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
Detail: https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}  (jobAd.sections = JD)

Seed companies below were each verified live (2026-07-14) to return >0 postings.
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

# Company identifiers verified live to return >0 postings via the public API.
# Case-sensitive. Many hire in India / remote (Canva, Freshworks, Swiggy, Grab,
# DeliveryHero, Wise, Experian, NielsenIQ, Bosch, Bytedance).
SMARTRECRUITERS_COMPANIES = [
    {"id": "BoschGroup", "name": "Bosch"},
    {"id": "DeliveryHero", "name": "Delivery Hero"},
    {"id": "PublicStorage", "name": "Public Storage"},
    {"id": "Experian", "name": "Experian"},
    {"id": "AveryDennison", "name": "Avery Dennison"},
    {"id": "Wise", "name": "Wise"},
    {"id": "NielsenIQ", "name": "NielsenIQ"},
    {"id": "Grab", "name": "Grab"},
    {"id": "WesternDigital", "name": "Western Digital"},
    {"id": "Canva", "name": "Canva"},
    {"id": "Freshworks", "name": "Freshworks"},
    {"id": "McDonaldsCorporation", "name": "McDonald's"},
    {"id": "Visa", "name": "Visa"},
    {"id": "Swiggy", "name": "Swiggy"},
    {"id": "Omio", "name": "Omio"},
    {"id": "Bytedance", "name": "ByteDance"},
    {"id": "Thales", "name": "Thales"},
    {"id": "Dataiku", "name": "Dataiku"},
    {"id": "Wayfair", "name": "Wayfair"},
    # Added 2026-07-17, each verified live to return >0 postings.
    # Many hire heavily in India / Bengaluru (SanDisk, Renesas, Eurofins,
    # Nexthink, Nielsen, Informa, AECOM, ServiceNow, LinkedIn, Arista).
    {"id": "ServiceNow", "name": "ServiceNow"},
    {"id": "AristaNetworks", "name": "Arista Networks"},
    {"id": "LinkedIn3", "name": "LinkedIn"},
    {"id": "MicroStrategy1", "name": "MicroStrategy"},
    {"id": "Uber", "name": "Uber"},
    {"id": "SmithsGroup2", "name": "Smiths Group"},
    {"id": "Sandisk", "name": "SanDisk"},
    {"id": "RenesasElectronics", "name": "Renesas Electronics"},
    {"id": "Eurofins", "name": "Eurofins"},
    {"id": "Nexthink", "name": "Nexthink"},
    {"id": "TheNielsenCompany", "name": "Nielsen"},
    {"id": "InformaGroupPlc", "name": "Informa"},
    {"id": "AECOM2", "name": "AECOM"},
    {"id": "EgisGroup", "name": "Egis Group"},
    {"id": "AbbVie", "name": "AbbVie"},
    {"id": "Wabtec", "name": "Wabtec"},
    {"id": "Continental", "name": "Continental"},
    {"id": "Sixt", "name": "Sixt"},
    {"id": "Alten", "name": "Alten"},
    {"id": "Devoteam", "name": "Devoteam"},
    {"id": "Atos1", "name": "Atos"},
    {"id": "Endava", "name": "Endava"},
    {"id": "Sutherland", "name": "Sutherland"},
    {"id": "Ubisoft2", "name": "Ubisoft"},
    {"id": "Believe", "name": "Believe"},
    {"id": "Trivago2", "name": "Trivago"},
    {"id": "softwaremind", "name": "Software Mind"},
    {"id": "sigmasoftware2", "name": "Sigma Software"},
    {"id": "Devexperts", "name": "Devexperts"},
    {"id": "CapTechConsulting", "name": "CapTech"},
    {"id": "Prosum2", "name": "Prosum"},
    {"id": "RebelFoods", "name": "Rebel Foods"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}

DEFAULT_LOCATIONS = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India", "Hyderabad", "Pune"]

# --- Role filtering (balanced: keep eng roles, drop clearly-senior ones) -----
ROLE_SUBSTRINGS = [
    "software", "engineer", "developer", "backend", "back end", "back-end",
    "frontend", "front end", "front-end", "full stack", "full-stack",
    "data engineer", "platform", "devops", "site reliability",
]
ROLE_WORDS = ["ml", "ai", "sde", "sre"]  # matched on word boundaries
SENIOR_SUBSTRINGS = [
    "senior", "staff", "principal", "lead", "director", "manager", "head of", "architect",
]
SENIOR_WORDS = ["sr", "vp"]  # matched on word boundaries

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
    """Parse an ISO-8601 (or date-only) string into a tz-aware UTC datetime."""
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


def _build_location(loc: dict) -> tuple[str, bool]:
    """Return (location_string, is_remote) from a SmartRecruiters location object."""
    remote = bool(loc.get("remote"))
    full = loc.get("fullLocation") or ", ".join(
        p for p in [loc.get("city"), loc.get("region"), loc.get("country")] if p
    )
    full = (full or "").strip(", ").strip()
    if remote and "remote" not in full.lower():
        full = f"{full} (Remote)".strip() if full else "Remote"
    return full, (remote or _is_remote(full))


def _construct_url(company_id: str, posting_id: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"https://jobs.smartrecruiters.com/{company_id}/{posting_id}-{slug}"


async def _fetch_detail(client: httpx.AsyncClient, company_id: str, posting_id: str) -> tuple[str, str]:
    """Return (canonical_url, description) from the posting detail endpoint. Best-effort."""
    url = ""
    description = ""
    try:
        resp = await client.get(
            f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{posting_id}"
        )
        if resp.status_code == 200:
            det = resp.json()
            url = det.get("postingUrl") or det.get("applyUrl") or ""
            sections = (det.get("jobAd") or {}).get("sections", {}) or {}
            parts = []
            for key in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"):
                txt = (sections.get(key) or {}).get("text", "")
                if txt:
                    parts.append(txt)
            description = _clean_html(" ".join(parts))
    except Exception:
        pass
    return url, description


async def _scrape_company(
    client: httpx.AsyncClient,
    company_id: str,
    company_name: str,
    target_locations: list[str],
    max_age_days: int,
    max_pages: int = 3,
    max_detail: int = 40,
) -> list[JobListing]:
    """Scrape one SmartRecruiters company for matching postings."""
    now = datetime.now(timezone.utc)
    matched: list[dict] = []

    for page in range(max_pages):
        try:
            resp = await client.get(
                f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings",
                params={"limit": 100, "offset": page * 100},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("smartrecruiters: %s page %d failed: %s", company_id, page, exc)
            break

        content = data.get("content", []) or []
        if not content:
            break

        page_has_fresh = False
        for posting in content:
            posted = _parse_dt(posting.get("releasedDate"))
            fresh = posted is None or (now - posted).total_seconds() / 86400 <= max_age_days
            if fresh:
                page_has_fresh = True

            title = posting.get("name", "")
            if not _role_ok(title):
                continue
            location, remote = _build_location(posting.get("location", {}) or {})
            if not _location_ok(location, target_locations):
                continue
            if posted is not None and (now - posted).total_seconds() / 86400 > max_age_days:
                continue
            matched.append({"posting": posting, "location": location, "remote": remote, "posted": posted})

        total = data.get("totalFound", 0)
        if (page + 1) * 100 >= total:
            break
        # Postings are returned newest-first; if a whole page is already stale, stop.
        if not page_has_fresh:
            break

    # Fetch JD + canonical URL for matched postings (bounded concurrency).
    detail_sem = asyncio.Semaphore(5)

    async def build(entry: dict) -> JobListing:
        posting = entry["posting"]
        posting_id = str(posting.get("id", ""))
        title = posting.get("name", "")
        title_lower = title.lower()
        async with detail_sem:
            url, description = await _fetch_detail(client, company_id, posting_id)
        if not url:
            url = _construct_url(company_id, posting_id, title)
        if not description:
            bits = [
                (posting.get("function") or {}).get("label", ""),
                (posting.get("industry") or {}).get("label", ""),
                (posting.get("typeOfEmployment") or {}).get("label", ""),
            ]
            description = " | ".join(b for b in bits if b)

        is_intern = "intern" in title_lower
        if is_intern:
            seniority = "intern"
        elif any(k in title_lower for k in ("junior", "associate", "graduate", "entry", "new grad")):
            seniority = "junior"
        else:
            seniority = ""

        return JobListing(
            id=f"smartrecruiters-{posting_id}",
            title=title,
            company=company_name,
            location=entry["location"],
            url=url,
            source="smartrecruiters",
            description=description,
            posted_date=entry["posted"],
            is_remote=entry["remote"],
            employment_type="internship" if is_intern else "full-time",
            seniority=seniority,
            company_size="enterprise",
        )

    tasks = [build(e) for e in matched[:max_detail]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, JobListing)]


async def scrape_smartrecruiters(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50000,
    max_concurrent: int = 8,
) -> list[JobListing]:
    """Scrape all configured SmartRecruiters companies concurrently.

    min_salary_inr is accepted for a uniform signature but not used to filter
    (comp data is sparse on this source).
    """
    if target_locations is None:
        target_locations = list(DEFAULT_LOCATIONS)

    all_jobs: list[JobListing] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(company: dict) -> list[JobListing]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
                    return await _scrape_company(
                        client,
                        company["id"],
                        company["name"],
                        target_locations,
                        max_age_days,
                    )
            except Exception as exc:
                logger.warning("smartrecruiters: %s failed: %s", company["id"], exc)
                return []

    results = await asyncio.gather(
        *[scrape_one(c) for c in SMARTRECRUITERS_COMPANIES], return_exceptions=True
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
