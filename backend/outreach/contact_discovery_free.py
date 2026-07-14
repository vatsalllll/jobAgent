"""Free contact discovery fallbacks — no paid API keys required.

Sources:
  - GitHub API (free, 60 req/hour unauth, 5000 with token)
  - Team page scraping (HTTP requests, no auth)
  - Email pattern inference from names + MX verification

All functions gracefully degrade when rate-limited or blocked.
"""

import asyncio
import logging
import os
import re
from typing import Optional

import httpx

from outreach.email_verify import has_mx_record

logger = logging.getLogger(__name__)


def _gh_headers() -> dict:
    """GitHub API headers, with auth when a token is available (60→5000 req/hr)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JobAgent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        from config import settings
        token = os.getenv("GITHUB_TOKEN") or getattr(settings, "github_token", "")
    except Exception:
        token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

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
                headers=_gh_headers(),
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
                    headers=_gh_headers(),
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


async def _github_commit_emails(company_name: str, domain: str, max_contacts: int = 5) -> list[dict]:
    """Extract real developer emails from a company's public GitHub org commits.

    Bounded to a handful of requests. Prefers commit-author emails whose domain matches
    the company domain (strong verification signal); skips GitHub noreply addresses.
    """
    slug = re.sub(r"[^a-z0-9-]", "", company_name.lower().replace(" ", "-"))
    if not slug:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            repos_resp = await client.get(
                f"https://api.github.com/orgs/{slug}/repos?sort=pushed&per_page=3",
                headers=_gh_headers(),
            )
            if repos_resp.status_code != 200:
                return []
            repos = repos_resp.json()
            if not isinstance(repos, list):
                return []

            for repo in repos[:3]:
                full = repo.get("full_name")
                if not full:
                    continue
                commits_resp = await client.get(
                    f"https://api.github.com/repos/{full}/commits?per_page=20",
                    headers=_gh_headers(),
                )
                if commits_resp.status_code != 200:
                    continue
                for c in commits_resp.json():
                    commit = (c or {}).get("commit", {})
                    author = commit.get("author", {}) or {}
                    email = (author.get("email") or "").strip().lower()
                    name = (author.get("name") or "").strip()
                    if not email or "@" not in email or email in seen:
                        continue
                    if email.endswith("noreply.github.com") or "users.noreply" in email:
                        continue
                    email_domain = email.split("@")[1]
                    # Only keep emails that plausibly belong to the company.
                    if domain and email_domain != domain.lower():
                        continue
                    if not domain and not has_mx_record(email_domain):
                        continue
                    seen.add(email)
                    results.append({
                        "email": email,
                        "name": name,
                        "position": "",
                        "source": "github_public",
                        "type": "personal",
                        "confidence": "medium",
                    })
                    if len(results) >= max_contacts:
                        return results
    except Exception as e:
        logger.warning(f"GitHub commit-email lookup failed for {company_name}: {e}")
    return results


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
                    # Look for common team page patterns, e.g.
                    # ">John Doe -", ">Jane Smith (", ">Alex Ng<"
                    # Intentionally simple; will have false positives.
                    name_patterns = re.findall(
                        r">\s*([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[<(\-—|]",
                        resp.text,
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

    # GitHub (free, most reliable) — profile emails + commit-author emails in parallel.
    github_users, commit_emails = await asyncio.gather(
        _github_search_users(company_name),
        _github_commit_emails(company_name, domain),
    )
    contacts.extend(commit_emails)   # domain-matched real emails first
    contacts.extend(github_users)

    # Team page scraping (heuristic, low confidence)
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
