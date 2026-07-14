import asyncio
import re
from urllib.parse import urlparse
from typing import Optional

import httpx

from config import settings
from outreach.google_search import find_linkedin_contacts, find_careers_page
from outreach.contact_discovery_free import find_contacts_free

COMMON_DOMAINS = {
    "stripe.com": "stripe.com", "notion.so": "notion.so", "figma.com": "figma.com",
    "vercel.com": "vercel.com", "datadoghq.com": "datadoghq.com", "reddit.com": "reddit.com",
    "discord.com": "discord.com", "roblox.com": "roblox.com", "brex.com": "brex.com",
    "ramp.com": "ramp.com", "postman.com": "postman.com", "slice.com": "slice.com",
    "duolingo.com": "duolingo.com", "instacart.com": "instacart.com", "zoho.com": "zoho.com",
    "atlassian.com": "atlassian.com", "spotify.com": "spotify.com", "rippling.com": "rippling.com",
    "canva.com": "canva.com", "plaid.com": "plaid.com", "intercom.com": "intercom.com",
    "monday.com": "monday.com", "grammarly.com": "grammarly.com", "benchling.com": "benchling.com",
    "amplitude.com": "amplitude.com", "coinbase.com": "coinbase.com",
}

CONTACT_PATTERNS = [
    "founders@{domain}",
    "hiring@{domain}",
    "recruiting@{domain}",
    "talent@{domain}",
    "careers@{domain}",
    "jobs@{domain}",
    "team@{domain}",
    "work@{domain}",
    "hello@{domain}",
]

FOUNDER_TITLES = [
    "founder", "co-founder", "cofounder", "ceo", "cto", "chief executive",
    "chief technology", "vp engineering", "vp eng", "head of engineering",
    "engineering manager", "tech lead", "technical lead",
]

RECRUITER_TITLES = [
    "recruiter", "talent", "hiring", "people", "hr ", "human resources",
    "recruiting", "talent acquisition", "sourcer",
]


# Sources whose email is a REAL, observed address (not a guess).
VERIFIED_SOURCES = {"hunter", "github_public", "google", "linkedin"}
# Sources whose email is a GUESS (permutation of a name) — high bounce risk.
GUESSED_PERSONAL_SOURCES = {"yc_api", "team_page_scrape"}


def _is_verified(contact: dict) -> bool:
    source = (contact.get("source") or "").lower()
    conf = (contact.get("confidence") or "low").lower()
    if source == "hunter":
        return conf in ("high", "medium")
    return source in VERIFIED_SOURCES


def _score_contact(contact: dict) -> int:
    """Rank contacts so that VERIFIED real emails always beat guessed ones, and
    deliverable role-addresses on a known domain beat guessed personal addresses.

    This fixes the prior inversion where a guessed `founders@` pattern or a guessed
    YC-founder `first.last@` outranked a real, GitHub-verified personal email.
    """
    position = (contact.get("position") or "").lower()
    email = (contact.get("email") or "").lower()
    confidence = (contact.get("confidence") or "low").lower()
    source = (contact.get("source") or "").lower()

    if not email:
        return 0
    verified = _is_verified(contact)

    # TIER 1 — verified real personal addresses. Title/confidence bonuses apply ONLY here,
    # because ranking a *guess* by the person's title is what caused the old inversion.
    if verified:
        base = {"hunter": 25, "github_public": 22, "google": 18, "linkedin": 18}.get(source, 16)
        bonus = 0
        if confidence == "high":
            bonus += 6
        elif confidence == "medium":
            bonus += 3
        if any(t in position for t in FOUNDER_TITLES):
            bonus += 6
        elif any(t in position for t in RECRUITER_TITLES):
            bonus += 5
        if (contact.get("type") or "").lower() == "personal":
            bonus += 2
        return base + bonus

    # TIER 2 — deliverable role addresses on a real domain (low bounce risk).
    if source == "pattern":
        if any(p in email for p in ["hiring", "recruit", "talent"]):
            return 10
        if any(p in email for p in ["careers", "jobs"]):
            return 8
        if "founder" in email:
            return 7
        return 6  # team@ / hello@ / work@

    # TIER 3 — guessed personal addresses (high bounce risk; should_send blocks these).
    if source == "yc_api":
        return 4
    if source == "team_page_scrape":
        return 2
    return 1


ATS_DOMAINS = [
    "ashbyhq.com", "greenhouse.io", "boards.greenhouse.io",
    "lever.co", "jobs.lever.co", "myworkdayjobs.com", "workday.com",
    "workatastartup.com", "angel.co", "wellfound.com",
    "workable.com", "smartrecruiters.com", "applytojob.com",
    "breezy.hr", "recruitee.com", "apply.workable.com",
    "jobvite.com", "icims.com", "taleo.net", "bamboohr.com",
    "jazz.co", "jazzhr.com", "teamtailor.com", "personio.de",
    "join.com", "rippling.com", "ripplingats.com", "paylocity.com",
    "successfactors.com", "eightfold.ai", "gh_jid", "avature.net",
]


def _is_ats_domain(domain: str) -> bool:
    domain_lower = (domain or "").lower()
    return any(ats in domain_lower for ats in ATS_DOMAINS)


def _resolve_domain(company_name: str, company_url: str = "") -> tuple[str, str]:
    """Return (domain, origin) where origin is 'url' | 'known' | 'guessed' | ''.

    Origin lets callers decide whether the domain is trustworthy enough to email:
    'url' and 'known' are real; 'guessed' is a {name}.com guess and must NOT be
    auto-emailed (it may belong to an unrelated company).
    """
    clean = (company_name or "").lower().strip()
    clean = re.sub(r"\s*\([^)]*\)", "", clean)
    clean = re.sub(r"[^a-z0-9]", "", clean)

    if company_url:
        parsed = urlparse(company_url)
        netloc = parsed.netloc
        if not netloc and parsed.path:
            netloc = parsed.path.split("/")[0]
        netloc = netloc.replace("www.", "") if netloc else ""
        if netloc and not _is_ats_domain(netloc) and "." in netloc:
            return netloc, "url"

    for known_domain in COMMON_DOMAINS:
        if clean and (clean in known_domain or known_domain.startswith(clean)):
            return COMMON_DOMAINS[known_domain], "known"

    if not clean:
        return "", ""
    guessed = f"{clean}.com"
    if _is_ats_domain(guessed):
        return "", ""
    return guessed, "guessed"


async def find_company_domain(company_name: str, company_url: str = "") -> str:
    return _resolve_domain(company_name, company_url)[0]


async def _find_yc_founders(company_name: str) -> list[dict]:
    if not company_name:
        return []
    try:
        slug = re.sub(r"[^a-z0-9-]", "", company_name.lower().replace(" ", "-").replace(".", ""))
        if not slug:
            return []
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.ycombinator.com/v0.1/companies/{slug}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            founders = data.get("founders", [])
            results = []
            for f in founders:
                name = f.get("name", "")
                if not name:
                    continue
                parts = name.split()
                if len(parts) >= 2:
                    first, last = parts[0], parts[-1]
                    email_guess = f"{first.lower()}.{last.lower()}"
                else:
                    email_guess = name.lower().replace(" ", ".")
                results.append({
                    "email": email_guess,
                    "type": "founder",
                    "confidence": "medium",
                    "name": name,
                    "position": f.get("title", "Founder"),
                    "source": "yc_api",
                })
            return results
    except Exception:
        return []


async def _search_hunter(domain: str, api_key: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": api_key, "limit": 10},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for email_data in data.get("data", {}).get("emails", []):
                conf = email_data.get("confidence", 0)
                results.append({
                    "email": email_data.get("value", ""),
                    "type": email_data.get("type", "personal"),
                    "confidence": "high" if conf > 80 else "medium" if conf > 50 else "low",
                    "name": f"{email_data.get('first_name', '')} {email_data.get('last_name', '')}".strip(),
                    "position": email_data.get("position", ""),
                    "source": "hunter",
                })
            return results
    except Exception:
        return []


async def discover_company_info(company_name: str, company_url: str = "") -> dict:
    """
    Full company info discovery:
    - Email contacts (Hunter + patterns + YC API)
    - LinkedIn contacts (Google Search)
    - Careers page URL
    - Domain
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return {
            "domain": "",
            "contacts": [],
            "linkedin_contacts": [],
            "careers_page": "",
        }

    domain, domain_origin = _resolve_domain(company_name, company_url)

    contacts = []
    linkedin_contacts = []
    careers_page = ""

    safe_domain = domain if domain and not _is_ats_domain(domain) else ""
    domain_guessed = domain_origin == "guessed"

    if safe_domain:
        for pattern in CONTACT_PATTERNS:
            email = pattern.replace("{domain}", safe_domain)
            contacts.append({
                "email": email,
                "type": pattern.split("@{")[0],
                "confidence": "low",
                "source": "pattern",
            })

    hunter_key = settings.hunter_api_key or ""
    if hunter_key and safe_domain:
        hunter_results = await _search_hunter(safe_domain, hunter_key)
        contacts = hunter_results + contacts

    yc_founders = await _find_yc_founders(company_name)
    if yc_founders:
        for f in yc_founders:
            if "@" not in f["email"]:
                f["email"] = f"{f['email']}@{safe_domain}" if safe_domain else f"{f['email']}@unknown.com"
        contacts = yc_founders + contacts

    free_contacts = await find_contacts_free(company_name, safe_domain)
    if free_contacts:
        contacts = free_contacts + contacts

    contacts.sort(key=_score_contact, reverse=True)

    if settings.google_search_api_key and settings.google_cse_id:
        linkedin_contacts = await find_linkedin_contacts(company_name, safe_domain)
        careers_page = await find_careers_page(company_name, company_url)

    return {
        "domain": safe_domain,
        "domain_origin": domain_origin,
        "domain_guessed": domain_guessed,
        "contacts": contacts[:10],
        "linkedin_contacts": linkedin_contacts,
        "careers_page": careers_page,
    }


def get_best_contact(contacts: list[dict]) -> dict:
    if not contacts:
        return {"email": "", "type": "unknown", "confidence": "none", "source": "none", "name": "", "position": ""}

    # Keep only usable contacts (real address, non-ATS domain) BEFORE picking the best,
    # so an ATS-domain top-scorer doesn't cause us to discard a perfectly good non-ATS one.
    usable = []
    for c in contacts:
        e = (c.get("email") or "").strip()
        if "@" not in e:
            continue
        if _is_ats_domain(e.split("@")[1].lower()):
            continue
        usable.append(c)

    if not usable:
        return {"email": "", "type": "unknown", "confidence": "none", "source": "none", "name": "", "position": ""}

    best = sorted(usable, key=_score_contact, reverse=True)[0]
    email = (best.get("email") or "").strip()

    return {
        "email": email,
        "type": (best.get("type") or "unknown").strip(),
        "confidence": (best.get("confidence") or "none").strip(),
        "source": (best.get("source") or "none").strip(),
        "name": (best.get("name") or "").strip(),
        "position": (best.get("position") or "").strip(),
        "verified": _is_verified(best),
        "is_role_address": (best.get("source") or "").lower() == "pattern",
    }


def should_send(best_contact: dict, domain_guessed: bool) -> tuple[bool, str]:
    """Decide whether it is safe to auto-email this contact.

    Returns (ok, reason). We DO NOT auto-send when:
      - there is no email, or it's an ATS address (already filtered upstream),
      - the domain was merely GUESSED ({company}.com) — could be an unrelated company,
      - the address is a GUESSED PERSONAL address (yc_api / team-scrape) that isn't verified
        (high bounce risk); a deliverable role address (careers@/hiring@) on a real domain is OK.
    MX verification is done separately by the caller (email_verify).
    """
    email = (best_contact.get("email") or "").strip()
    if not email or "@" not in email:
        return False, "no_contact_email"

    source = (best_contact.get("source") or "").lower()
    verified = bool(best_contact.get("verified"))

    if domain_guessed and not verified:
        return False, "domain_guessed"
    if source in GUESSED_PERSONAL_SOURCES and not verified:
        return False, "guessed_personal_address"
    return True, "ok"


async def test_hunter() -> dict:
    hunter_key = settings.hunter_api_key or ""
    if not hunter_key:
        return {"status": "no_key", "message": "HUNTER_API_KEY not configured"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/account",
                params={"api_key": hunter_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": "ok",
                    "plan": data.get("data", {}).get("plan_name", "unknown"),
                    "requests_left": data.get("data", {}).get("requests_left", 0),
                    "calls": data.get("data", {}).get("calls", {}).get("used", 0),
                }
            elif resp.status_code == 401:
                return {"status": "invalid_key", "message": "Hunter.io API key is invalid"}
            else:
                return {"status": "error", "code": resp.status_code, "message": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
