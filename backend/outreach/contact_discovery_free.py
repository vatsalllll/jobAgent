"""Free contact discovery fallbacks — no paid API keys required.

Sources:
  - GitHub API (free, 60 req/hour unauth, 5000 with token)
  - Team page scraping (HTTP requests, no auth)
  - Email pattern inference from names + MX verification

All functions gracefully degrade when rate-limited or blocked.
"""

import asyncio
import logging
import re
from typing import Optional

import httpx

from outreach.email_verify import has_mx_record

logger = logging.getLogger(__name__)

# Common email patterns for name → email inference
EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}@{domain}",
    "{f}{last}@{domain}",
    "{first}_{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}.{last}@{domain}",
]


def _infer_email(name: str, domain: str) -> list[str]:
    """Generate likely email addresses from a person's name and company domain."""
    if not name or not domain or "@" in domain:
        return []

    # Clean name
    name = name.lower().strip()
    name = re.sub(r"[^a-z\s]", "", name)
    parts = name.split()
    if len(parts) < 1:
        return []

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""
    f = first[0] if first else ""

    emails = []
    for pattern in EMAIL_PATTERNS:
        email = pattern.format(first=first, last=last, f=f, domain=domain)
        if email not in emails and "@" in email and email.count("@") == 1:
            emails.append(email)

    return emails


async def _github_search_users(company_name: str, max_results: int = 5) -> list[dict]:
    """Search GitHub for users who list this company in their profile.

    Free tier: 60 requests/hour without auth, 5000 with GITHUB_TOKEN.
    """
    query = f"type:user+company:{company_name.replace(' ', '+')}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.github.com/search/users?q={query}&per_page={max_results}",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("items", [])
            results = []
            for item in items:
                login = item.get("login", "")
                if not login:
                    continue
                # Fetch user profile for name and public email
                user_resp = await client.get(
                    f"https://api.github.com/users/{login}",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if user_resp.status_code != 200:
                    continue
                user = user_resp.json()
                public_email = (user.get("email") or "").strip().lower()
                name = (user.get("name") or "").strip()
                if public_email and "@" in public_email:
                    results.append({
                        "email": public_email,
                        "name": name or login,
                        "position": "",
                        "source": "github_public",
                        "type": "personal",
                        "confidence": "medium",
                        "github": user.get("html_url", ""),
                    })
            return results
    except Exception as e:
        logger.warning(f"GitHub search failed for {company_name}: {e}")
        return []


async def _scrape_team_page(domain: str) -> list[dict]:
    """Scrape company /about or /team page for employee names.

    Very heuristic — only works on simple static pages. No JS rendering.
    """
    if not domain or "." not in domain:
        return []

    candidates = []
    paths = ["/about", "/team", "/people", "/company"]

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for path in paths:
                url = f"https://{domain}{path}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    text = resp.text.lower()
                    # Look for common team page patterns
                    # e.g., "John Doe - CTO", "Jane Smith (Engineering)"
                    # This is intentionally simple and will have false positives
                    name_patterns = re.findall(
                        r">([a-z]+\s+[a-z]+)\s*[-—(|<",
                        resp.text,
                        re.IGNORECASE,
                    )
                    for name in name_patterns[:5]:
                        clean_name = name.strip()
                        if len(clean_name.split()) == 2 and len(clean_name) > 5:
                            candidates.append({
                                "name": clean_name,
                                "email": "",
                                "position": "",
                                "source": "team_page_scrape",
                                "type": "personal",
                                "confidence": "low",
                            })
                    if candidates:
                        break
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Team page scrape failed for {domain}: {e}")

    # Try to infer emails for discovered names
    results = []
    seen_emails = set()
    for c in candidates:
        inferred = _infer_email(c["name"], domain)
        for email in inferred:
            if email not in seen_emails:
                seen_emails.add(email)
                if has_mx_record(email.split("@")[1]):
                    results.append({
                        **c,
                        "email": email,
                        "confidence": "low",
                    })
    return results[:5]


async def find_contacts_free(company_name: str, domain: str) -> list[dict]:
    """Find contacts using only free sources.

    Order of priority:
      1. GitHub public emails (verified real addresses)
      2. Team page scraping + pattern inference (low confidence)

    Returns list of contact dicts, same shape as contact_finder.py output.
    """
    contacts = []

    # GitHub (free, most reliable)
    github_contacts = await _github_search_users(company_name)
    contacts.extend(github_contacts)

    # Team page scraping (heuristic)
    if domain:
        scraped = await _scrape_team_page(domain)
        contacts.extend(scraped)

    # Deduplicate by email
    seen = set()
    unique = []
    for c in contacts:
        email = c.get("email", "").lower()
        if email and email not in seen:
            seen.add(email)
            unique.append(c)

    logger.info(f"Free contact discovery for {company_name}: found {len(unique)} contacts")
    return unique
