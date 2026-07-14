import asyncio
import re
from urllib.parse import urlparse
from typing import Optional

import httpx

from config import settings

GOOGLE_CSE_API = "https://www.googleapis.com/customsearch/v1"

CAREERS_PATHS = [
    "/careers", "/jobs", "/about#jobs", "/about#careers",
    "/opportunities", "/work-with-us", "/join-us", "/team",
    "/hiring", "/open-positions", "/positions", "/job-openings",
]

# Unambiguous rejection phrases. NOTE: "thank you for your interest" was removed — it is a
# common OPENING line in positive/scheduling emails too, and checking it first mislabeled
# interview invites as rejections.
REJECTION_KEYWORDS = [
    "unfortunately", "not moving forward", "move forward with other candidates",
    "regret to inform", "we regret", "decided not to", "not be moving forward",
    "not selected", "not a fit", "not the right fit", "not proceeding",
    "position has been filled", "role has been filled", "no longer under consideration",
    "pursue other candidates", "decided to proceed with other",
]

SECOND_ROUND_KEYWORDS = [
    "interview", "schedule a", "next step", "screening call", "phone screen",
    "zoom", "google meet", "calendar", "book a time", "your availability",
    "set up a call", "hop on a call", "second round", "next round",
    "hiring manager would like", "technical interview", "coding challenge",
    "take-home", "pair programming", "system design round", "onsite", "virtual onsite",
    "when are you free", "quick chat",
]


def _has_keywords(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def classify_email(subject: str, body: str) -> str:
    """Classify a reply as rejected, second_round, or unknown.

    Interview signals are checked BEFORE weak rejection cues, because positive emails
    frequently open with polite boilerplate. A strong, unambiguous rejection phrase still
    wins over an interview cue (handles "unfortunately we won't be interviewing you").
    """
    full_text = f"{subject}\n{body}".lower()

    strong_reject = _has_keywords(full_text, REJECTION_KEYWORDS)
    interview = _has_keywords(full_text, SECOND_ROUND_KEYWORDS)

    if interview and not strong_reject:
        return "second_round"
    if strong_reject:
        return "rejected"
    if interview:
        return "second_round"
    return "unknown"


async def search_google(query: str, num_results: int = 5) -> list[dict]:
    """Search Google via Custom Search API. Returns list of result items."""
    api_key = settings.google_search_api_key
    cse_id = settings.google_cse_id

    if not api_key or not cse_id:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                GOOGLE_CSE_API,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": min(num_results, 10),
                },
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("items", [])
            return [
                {
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
                for item in items
            ]
    except Exception:
        return []


async def find_linkedin_contacts(company_name: str, domain: str = "") -> list[dict]:
    """Find LinkedIn profiles for founders/recruiters at a company."""
    contacts = []

    queries = [
        f'site:linkedin.com/in/ "{company_name}" founder OR ceo OR cto',
        f'site:linkedin.com/in/ "{company_name}" recruiter OR hiring OR talent',
    ]

    for query in queries:
        results = await search_google(query, num_results=5)
        for r in results:
            link = r.get("link", "")
            if "linkedin.com/in/" not in link:
                continue

            title = r.get("title", "")
            snippet = r.get("snippet", "")

            name_match = re.search(r"([^|]+)\s*[-|]\s*LinkedIn", title)
            name = name_match.group(1).strip() if name_match else ""

            position = ""
            pos_match = re.search(r"-\s*([^|]+)\s*[-|]", title)
            if pos_match:
                position = pos_match.group(1).strip()
            elif snippet:
                pos_match = re.search(r"(CEO|CTO|Founder|Recruiter|Talent|Hiring)[^\.]*", snippet, re.IGNORECASE)
                if pos_match:
                    position = pos_match.group(0)

            role_type = "unknown"
            if any(k in position.lower() for k in ["founder", "ceo", "cto", "chief"]):
                role_type = "founder"
            elif any(k in position.lower() for k in ["recruiter", "talent", "hiring"]):
                role_type = "recruiter"

            contacts.append({
                "name": name,
                "position": position,
                "linkedin_url": link,
                "type": role_type,
                "source": "google_search",
            })

    seen = set()
    unique = []
    for c in contacts:
        if c["linkedin_url"] not in seen:
            seen.add(c["linkedin_url"])
            unique.append(c)

    return unique[:5]


async def find_careers_page(company_name: str, company_url: str = "") -> str:
    """Find the careers/jobs page for a company."""
    if company_url:
        parsed = urlparse(company_url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else f"https://{parsed.netloc}"
        if base:
            for path in CAREERS_PATHS:
                candidate = base + path
                try:
                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                        resp = await client.head(candidate)
                        if resp.status_code == 200:
                            return candidate
                except Exception:
                    continue

    domain = company_url.replace("https://", "").replace("http://", "").split("/")[0] if company_url else ""
    if not domain:
        domain = company_name.lower().replace(" ", "") + ".com"

    queries = [
        f'"{company_name}" careers site:{domain}',
        f'"{company_name}" jobs site:{domain}',
        f'"{company_name}" hiring site:{domain}',
    ]

    for query in queries:
        results = await search_google(query, num_results=3)
        for r in results:
            link = r.get("link", "")
            if any(kw in link.lower() for kw in ["career", "job", "hiring", "opportunit", "position"]):
                return link

    if company_url:
        parsed = urlparse(company_url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else f"https://{parsed.netloc}"
        return base + "/careers"

    return ""
