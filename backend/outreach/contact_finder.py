import asyncio
import re
from urllib.parse import urlparse
from typing import Optional

import httpx

from config import settings

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


def _score_contact(contact: dict) -> int:
    """Score a contact for relevance. Higher = better."""
    score = 0
    position = contact.get("position", "").lower()
    email = contact.get("email", "").lower()
    ctype = contact.get("type", "").lower()
    confidence = contact.get("confidence", "low")
    source = contact.get("source", "")

    if source == "hunter":
        score += 20
        if confidence == "high":
            score += 10
        elif confidence == "medium":
            score += 5

    for title in FOUNDER_TITLES:
        if title in position:
            score += 15
            break

    for title in RECRUITER_TITLES:
        if title in position:
            score += 12
            break

    if ctype == "personal" or "personal" in email:
        score += 8

    if any(p in email for p in ["founder", "ceo", "cto"]):
        score += 10
    elif any(p in email for p in ["hiring", "recruit", "talent"]):
        score += 8
    elif any(p in email for p in ["careers", "jobs"]):
        score += 4
    elif "hello" in email or "team" in email:
        score += 2

    return score


async def find_company_domain(company_name: str, company_url: str = "") -> str:
    clean = company_name.lower().strip()
    clean = re.sub(r"\s*\([^)]*\)", "", clean)
    clean = re.sub(r"[^a-z0-9]", "", clean)

    if company_url:
        parsed = urlparse(company_url)
        netloc = parsed.netloc or parsed.path.split("/")[0] if parsed.path else ""
        netloc = netloc.replace("www.", "")
        ats_domains = ["ashbyhq.com", "greenhouse.io", "boards.greenhouse.io",
                       "lever.co", "jobs.lever.co", "myworkdayjobs.com",
                       "workatastartup.com", "angel.co", "wellfound.com"]
        if not any(ats in netloc for ats in ats_domains) and "." in netloc:
            return netloc

    for known_domain in COMMON_DOMAINS:
        if clean in known_domain or known_domain.startswith(clean):
            return COMMON_DOMAINS[known_domain]

    return f"{clean}.com"


async def _find_yc_founders(company_name: str) -> list[dict]:
    """Try to find founders for YC companies via the YC API."""
    try:
        slug = company_name.lower().replace(" ", "-").replace(".", "")
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


async def discover_contact_emails(company_name: str, company_url: str = "") -> list[dict]:
    domain = await find_company_domain(company_name, company_url)
    contacts = []

    for pattern in CONTACT_PATTERNS:
        email = pattern.replace("{domain}", domain)
        contacts.append({
            "email": email,
            "type": pattern.split("@{")[0],
            "confidence": "low",
            "source": "pattern",
        })

    hunter_key = settings.hunter_api_key or ""
    if hunter_key:
        hunter_results = await _search_hunter(domain, hunter_key)
        contacts = hunter_results + contacts

    yc_founders = await _find_yc_founders(company_name)
    if yc_founders:
        for f in yc_founders:
            if "@" not in f["email"]:
                f["email"] = f"{f['email']}@{domain}"
        contacts = yc_founders + contacts

    contacts.sort(key=_score_contact, reverse=True)
    return contacts[:10]


def get_best_contact(contacts: list[dict], prefer_role: str = "founder") -> dict:
    if not contacts:
        return {"email": "", "type": "unknown", "confidence": "none", "source": "none", "name": "", "position": ""}

    sorted_contacts = sorted(contacts, key=_score_contact, reverse=True)
    best = sorted_contacts[0]

    if "@" not in best.get("email", ""):
        return {"email": "", "type": "unknown", "confidence": "none", "source": "none", "name": "", "position": ""}

    return best


async def test_hunter() -> dict:
    """Quick health check for Hunter.io credentials."""
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
