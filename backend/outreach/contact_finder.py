import asyncio
import re
from urllib.parse import urlparse

import httpx

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
    "careers@{domain}",
    "jobs@{domain}",
    "hiring@{domain}",
    "hello@{domain}",
    "founders@{domain}",
    "team@{domain}",
    "recruiting@{domain}",
    "talent@{domain}",
    "work@{domain}",
]


async def find_company_domain(company_name: str, company_url: str = "") -> str:
    clean = company_name.lower().strip()
    clean = re.sub(r"\s*\([^)]*\)", "", clean)
    clean = re.sub(r"[^a-z0-9]", "", clean)

    if company_url:
        try:
            parsed = urlparse(company_url)
            domain = parsed.netloc or parsed.path
            domain = domain.replace("www.", "").split("/")[0]
            if "." in domain:
                return domain
        except Exception:
            pass

    for known_domain, _ in COMMON_DOMAINS.items():
        if clean in known_domain or known_domain.startswith(clean):
            return known_domain

    return f"{clean}.com"


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

    hunter_key = __import__("os").getenv("HUNTER_API_KEY", "")
    if hunter_key:
        hunter_results = await _search_hunter(domain, hunter_key)
        for hr in hunter_results:
            hr["confidence"] = "high"
            hr["source"] = "hunter"
        contacts = hunter_results + contacts

    return contacts[:10]


async def _search_hunter(domain: str, api_key: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": api_key, "limit": 5},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for email_data in data.get("data", {}).get("emails", []):
                results.append({
                    "email": email_data.get("value", ""),
                    "type": email_data.get("type", "personal"),
                    "confidence": "high" if email_data.get("confidence", 0) > 80 else "medium",
                    "name": f"{email_data.get('first_name', '')} {email_data.get('last_name', '')}".strip(),
                    "position": email_data.get("position", ""),
                    "source": "hunter",
                })
            return results
    except Exception:
        return []


def get_best_contact(contacts: list[dict], prefer_role: str = "hiring") -> dict:
    for c in contacts:
        if c.get("type") == prefer_role or prefer_role in c.get("email", ""):
            return c
    for c in contacts:
        if c.get("confidence") == "high":
            return c
    if contacts:
        return contacts[0]
    return {"email": "", "type": "unknown", "confidence": "none", "source": "none"}
