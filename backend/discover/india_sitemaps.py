"""
India job-board XML sitemap sources: Cutshort, Hirist, foundit.

These boards publish public XML sitemaps of their job URLs. Unlike the JSON
API sources (greenhouse, workable, etc.), a sitemap exposes ONLY the job URL
(plus a <lastmod>) — there is no title / company / location / salary payload.
So we parse everything we can, best-effort, out of the URL slug:

    cutshort:  https://cutshort.io/job/<Title>-[City...]-<Company...>-<id>
               (city, when present, sits in the MIDDLE: title before, company after)
    hirist:    https://www.hirist.tech/j/<title-slug>-<numeric-id>
               (all-India tech board; no city in the slug)
    foundit:   https://www.foundit.in/job/<title>-<company>-<City...>-<numeric-id>
               (city, when present, sits at the END, just before the id)

Because a sitemap's <lastmod> is the crawl/entry-modification time and NOT a
reliable job posting date, we deliberately leave ``posted_date=None`` (do not
fake a date) — which means the ``max_age_days`` freshness filter is skipped for
these sources. ``description`` is left empty (no JD text in a sitemap).

Everything is best-effort and every entry function is crash-proof: on any
network/parse failure it logs a warning and returns whatever it has (never
raises). Matches the entry-function contract used by the other discover modules.
"""

import asyncio
import gzip
import html
import logging
import re
from typing import Optional

import httpx

from discover.models import JobListing

logger = logging.getLogger(__name__)

# Real browser-ish UA — a generic Python UA gets 403 on several of these hosts.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}

# Cap per source (parent spec: ~80). We stop building JobListings once we hit
# this many *matching* jobs, so we never materialise the full 40k-URL sitemap.
MAX_JOBS = 80

DEFAULT_TARGETS = [
    "Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram",
    "India", "Hyderabad", "Pune",
]

# Known India location tokens used to locate the city segment inside a slug.
# (Also includes remote/anywhere/worldwide so remote roles are detected.)
CITY_TOKENS = {
    "bengaluru", "bangalore", "gurgaon", "gurugram", "hyderabad", "pune",
    "mumbai", "navi", "delhi", "noida", "chennai", "kolkata", "ahmedabad",
    "coimbatore", "thiruvananthapuram", "trivandrum", "thane", "faridabad",
    "ghaziabad", "indore", "jaipur", "chandigarh", "mohali", "kochi", "cochin",
    "nagpur", "lucknow", "bhopal", "visakhapatnam", "vizag", "vadodara",
    "surat", "secunderabad", "telangana", "mysore", "mysuru", "mangalore",
    "mangaluru", "nashik", "rajkot", "kanpur", "patna", "guwahati",
    "bhubaneswar", "raipur", "dehradun", "goa",
    "remote", "india", "anywhere", "worldwide",
}

# Software / engineering role keywords (balanced — do NOT over-filter).
ROLE_KEYWORDS = [
    "software", "engineer", "developer", "backend", "frontend", "full stack",
    "fullstack", "data engineer", "platform", "devops", "sde", "sre", "ai", "ml",
]
# Short/ambiguous keywords that must match as whole words (avoid "ai" in "email",
# "ml" in "html", etc.).
_SHORT_ROLE = {"ai", "ml", "sde", "sre"}

# Clearly-senior titles to exclude (interns / new-grads are welcome, so no
# junior/intern keyword is required).
EXCLUDE_KEYWORDS = [
    "senior", "sr", "staff", "principal", "lead", "director",
    "manager", "vp", "head of", "architect",
]


def _humanize(tokens: list[str], title_case: bool) -> str:
    """Join slug tokens into a readable string."""
    text = " ".join(t for t in tokens if t)
    return text.title() if title_case else text


def _matches_role(title: str) -> bool:
    """True if the title looks like a non-senior software/engineering role."""
    t = title.lower()
    for kw in EXCLUDE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            return False
    for kw in ROLE_KEYWORDS:
        if kw in _SHORT_ROLE:
            if re.search(r"\b" + re.escape(kw) + r"\b", t):
                return True
        elif kw in t:
            return True
    return False


def _location_ok(location: str, targets: list[str]) -> bool:
    """Loose location filter — these are India boards, so India / any target
    city / remote all pass."""
    loc = location.lower()
    if any(t.lower() in loc for t in targets):
        return True
    if any(k in loc for k in ("remote", "india", "anywhere", "worldwide")):
        return True
    # Any recognised Indian city qualifies (it is, by definition, India).
    return any(word in CITY_TOKENS for word in loc.split())


def _strip_id(tokens: list[str], source: str) -> tuple[list[str], Optional[str]]:
    """Split the trailing external-id token off the slug tokens.

    Returns (tokens_without_id, external_id or None)."""
    if not tokens:
        return tokens, None
    last = tokens[-1]
    if source in ("hirist", "foundit"):
        if re.fullmatch(r"\d+", last):
            return tokens[:-1], last
    else:  # cutshort: 8-ish char alnum id (has a digit OR mixed upper+lower case)
        if re.fullmatch(r"[A-Za-z0-9]{5,}", last) and (
            any(c.isdigit() for c in last)
            or (any(c.islower() for c in last) and any(c.isupper() for c in last))
        ):
            return tokens[:-1], last
    return tokens, None


def _parse_slug(url: str, source: str) -> tuple[str, str, str, str, bool]:
    """Best-effort (title, company, location, external_id, is_remote) from a job URL."""
    slug = url.rstrip("/").split("/")[-1]
    raw_tokens = slug.split("-")
    tokens, ext_id = _strip_id(raw_tokens, source)
    if not ext_id:
        ext_id = slug  # fallback keeps ids unique for dedup
    tokens = [t for t in tokens if t]
    low = [t.lower() for t in tokens]
    title_case = source in ("hirist", "foundit")  # these slugs are lowercase
    is_remote = "remote" in slug.lower()

    title = _humanize(tokens, title_case)
    company = ""
    location = "India"

    if source == "cutshort":
        # City sits in the middle: title BEFORE it, company AFTER it.
        start = next((i for i, w in enumerate(low) if w in CITY_TOKENS), None)
        if start is not None:
            end = start
            while end < len(low) and low[end] in CITY_TOKENS:
                end += 1
            head = _humanize(tokens[start:end], title_case) or title
            location = head
            title = _humanize(tokens[:start], title_case) or title
            company = _humanize(tokens[end:], title_case)
    elif source == "foundit":
        # City sits at the end (just before the id): title/company BEFORE it.
        end = len(low)
        start = end
        while start > 0 and low[start - 1] in CITY_TOKENS:
            start -= 1
        if start < end:
            location = _humanize(tokens[start:end], title_case) or "India"
            title = _humanize(tokens[:start], title_case) or title
    # hirist: no city in slug → location stays "India".

    if "remote" in location.lower():
        is_remote = True
    return title, company, location, ext_id, is_remote


async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> Optional[bytes]:
    """GET a URL, returning raw bytes, or None on any failure (never raises)."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # network error, timeout, 4xx/5xx, Cloudflare, etc.
        logger.warning("india_sitemaps: fetch failed for %s: %s", url, exc)
        return None


def _decode_sitemap(raw: bytes, gzipped: bool) -> str:
    """Decode sitemap bytes to text, gunzipping only if still compressed.

    httpx auto-decompresses Content-Encoding: gzip responses, so a ``.gz`` URL
    may arrive already-decoded. We therefore sniff the gzip magic bytes and only
    decompress when needed — handling both negotiation outcomes."""
    if gzipped and raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            logger.warning("india_sitemaps: gunzip failed: %s", exc)
    return raw.decode("utf-8", "replace")


def _extract_locs(xml_text: str) -> list[str]:
    """Pull every <loc> URL out of a sitemap (regex — robust to big files/namespaces)."""
    return [html.unescape(m) for m in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml_text)]


def _build_jobs(
    urls: list[str],
    source: str,
    path_marker: str,
    target_locations: list[str],
) -> list[JobListing]:
    """Turn sitemap job URLs into filtered, de-duplicated JobListings (capped)."""
    jobs: list[JobListing] = []
    seen: set[str] = set()
    for url in urls:
        if path_marker not in url:
            continue
        title, company, location, ext_id, is_remote = _parse_slug(url, source)
        if not title or not _matches_role(title):
            continue
        if not _location_ok(location, target_locations):
            continue
        job_id = f"{source}-{ext_id}"
        if job_id in seen:
            continue
        seen.add(job_id)
        title_lower = title.lower()
        jobs.append(JobListing(
            id=job_id,
            title=title,
            company=company,
            location=location,
            url=url,
            source=source,
            description="",              # sitemaps carry no JD text
            posted_date=None,            # <lastmod> is not a reliable posting date
            is_remote=is_remote,
            employment_type="internship" if "intern" in title_lower else "full-time",
            seniority="intern" if "intern" in title_lower else "",
        ))
        if len(jobs) >= MAX_JOBS:
            break
    return jobs


async def _scrape_sitemap(
    source: str,
    sitemap_url: str,
    path_marker: str,
    gzipped: bool,
    target_locations: Optional[list[str]],
) -> list[JobListing]:
    """Shared driver: fetch one sitemap, parse it, return JobListings."""
    targets = target_locations or DEFAULT_TARGETS
    try:
        async with httpx.AsyncClient(
            timeout=30.0, headers=HEADERS, follow_redirects=True
        ) as client:
            raw = await _fetch_bytes(client, sitemap_url)
            if not raw:
                return []
            xml_text = _decode_sitemap(raw, gzipped)
            urls = _extract_locs(xml_text)
            jobs = _build_jobs(urls, source, path_marker, targets)
            logger.info("india_sitemaps: %s -> %d urls, %d jobs", source, len(urls), len(jobs))
            return jobs
    except Exception as exc:  # belt-and-suspenders: never raise out of the entry fn
        logger.warning("india_sitemaps: %s scrape failed: %s", source, exc)
        return []


async def scrape_cutshort(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50_000,
) -> list[JobListing]:
    """Cutshort (India) — parse https://cutshort.io/sitemap_jobs.xml job URLs."""
    return await _scrape_sitemap(
        source="cutshort",
        sitemap_url="https://cutshort.io/sitemap_jobs.xml",
        path_marker="/job/",
        gzipped=False,
        target_locations=target_locations,
    )


async def scrape_hirist(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50_000,
) -> list[JobListing]:
    """Hirist (India) — gzipped sitemap. Crawl-delay:10 is honoured by fetching once."""
    return await _scrape_sitemap(
        source="hirist",
        sitemap_url="https://hirist.tech/new_sitemap-j-1.xml.gz",
        path_marker="/j/",
        gzipped=True,
        target_locations=target_locations,
    )


async def _discover_foundit_sitemap(client: httpx.AsyncClient) -> str:
    """Discover foundit's real 'today's jobs' sitemap URL from robots.txt.

    Falls back to the known canonical URL if robots.txt is unavailable or does
    not advertise a today's-jobs sitemap."""
    fallback = "https://www.foundit.in/xmlsitemap/todays-jobs-sitemap.xml"
    raw = await _fetch_bytes(client, "https://www.foundit.in/robots.txt")
    if not raw:
        return fallback
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            candidate = line.split(":", 1)[1].strip()
            if "today" in candidate.lower():
                return candidate
    return fallback


async def scrape_foundit(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
    min_salary_inr: int = 50_000,
) -> list[JobListing]:
    """foundit (India) — discover today's-jobs sitemap via robots.txt, then parse."""
    targets = target_locations or DEFAULT_TARGETS
    try:
        async with httpx.AsyncClient(
            timeout=30.0, headers=HEADERS, follow_redirects=True
        ) as client:
            sitemap_url = await _discover_foundit_sitemap(client)
            raw = await _fetch_bytes(client, sitemap_url)
            if not raw:
                return []
            urls = _extract_locs(_decode_sitemap(raw, gzipped=False))
            jobs = _build_jobs(urls, "foundit", "/job/", targets)
            logger.info("india_sitemaps: foundit -> %s -> %d urls, %d jobs",
                        sitemap_url, len(urls), len(jobs))
            return jobs
    except Exception as exc:
        logger.warning("india_sitemaps: foundit scrape failed: %s", exc)
        return []
