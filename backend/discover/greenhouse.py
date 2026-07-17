"""
Greenhouse Job Board API client.
Public, unauthenticated, JSON — no partnership needed.
Pattern: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

# Common tech company Greenhouse board tokens (curated list)
# These are known companies that hire interns/juniors
GREENHOUSE_BOARDS = [
    # YC and well-known startups
    {"token": "openai", "name": "OpenAI"},
    {"token": "anthropic", "name": "Anthropic"},
    {"token": "vercel", "name": "Vercel"},
    {"token": "stripe", "name": "Stripe"},
    {"token": "notion", "name": "Notion"},
    {"token": "figma", "name": "Figma"},
    {"token": "datadog", "name": "Datadog"},
    {"token": "hashicorp", "name": "HashiCorp"},
    {"token": "doordash", "name": "DoorDash"},
    {"token": "instacart", "name": "Instacart"},
    {"token": "reddit", "name": "Reddit"},
    {"token": "roblox", "name": "Roblox"},
    {"token": "discord", "name": "Discord"},
    {"token": "duolingo", "name": "Duolingo"},
    {"token": "brex", "name": "Brex"},
    {"token": "ramp", "name": "Ramp"},
    {"token": "linear", "name": "Linear"},
    {"token": "vercel", "name": "Vercel"},
    {"token": "replicate", "name": "Replicate"},
    {"token": "huggingface", "name": "Hugging Face"},
    {"token": "cohere", "name": "Cohere"},
    {"token": "perplexity", "name": "Perplexity"},
    {"token": "cursor", "name": "Cursor"},
    {"token": "windsurf", "name": "Windsurf"},
    # India-based / India-hiring
    {"token": "postman", "name": "Postman"},
    {"token": "browserstack", "name": "BrowserStack"},
    {"token": "hasura", "name": "Hasura"},
    {"token": "chargebee", "name": "Chargebee"},
    {"token": "freshworks", "name": "Freshworks"},
    {"token": "zoho", "name": "Zoho"},
    {"token": "razorpay", "name": "Razorpay"},
    {"token": "cred", "name": "CRED"},
    {"token": "swiggy", "name": "Swiggy"},
    {"token": "zerodha", "name": "Zerodha"},
    {"token": "slice", "name": "Slice"},
    {"token": "smallcase", "name": "Smallcase"},
    {"token": "phonepe", "name": "PhonePe"},
    {"token": "groww", "name": "Groww"},
    # AI / ML companies (verified live 2026-07)
    {"token": "scaleai", "name": "Scale AI"},
    {"token": "togetherai", "name": "Together AI"},
    {"token": "fireworksai", "name": "Fireworks AI"},
    {"token": "gleanwork", "name": "Glean"},
    {"token": "coreweave", "name": "CoreWeave"},
    {"token": "assemblyai", "name": "AssemblyAI"},
    {"token": "speechmatics", "name": "Speechmatics"},
    {"token": "humeai", "name": "Hume AI"},
    {"token": "stabilityai", "name": "Stability AI"},
    # Well-known scaleups / remote-friendly tech
    {"token": "databricks", "name": "Databricks"},
    {"token": "airtable", "name": "Airtable"},
    {"token": "gitlab", "name": "GitLab"},
    {"token": "cloudflare", "name": "Cloudflare"},
    {"token": "coinbase", "name": "Coinbase"},
    {"token": "robinhood", "name": "Robinhood"},
    {"token": "affirm", "name": "Affirm"},
    {"token": "chime", "name": "Chime"},
    {"token": "gusto", "name": "Gusto"},
    {"token": "checkr", "name": "Checkr"},
    {"token": "samsara", "name": "Samsara"},
    {"token": "elastic", "name": "Elastic"},
    {"token": "mongodb", "name": "MongoDB"},
    {"token": "dropbox", "name": "Dropbox"},
    {"token": "asana", "name": "Asana"},
    {"token": "twitch", "name": "Twitch"},
    {"token": "lyft", "name": "Lyft"},
    {"token": "airbnb", "name": "Airbnb"},
    {"token": "pinterest", "name": "Pinterest"},
    {"token": "nextdoor", "name": "Nextdoor"},
    {"token": "faire", "name": "Faire"},
    {"token": "fivetran", "name": "Fivetran"},
    {"token": "webflow", "name": "Webflow"},
    {"token": "calendly", "name": "Calendly"},
    {"token": "lattice", "name": "Lattice"},
    {"token": "carta", "name": "Carta"},
    {"token": "verkada", "name": "Verkada"},
    {"token": "remotecom", "name": "Remote"},
    # Data / infra / developer tools
    {"token": "grafanalabs", "name": "Grafana Labs"},
    {"token": "tailscale", "name": "Tailscale"},
    {"token": "planetscale", "name": "PlanetScale"},
    {"token": "cockroachlabs", "name": "Cockroach Labs"},
    {"token": "clickhouse", "name": "ClickHouse"},
    {"token": "starburst", "name": "Starburst"},
    {"token": "singlestore", "name": "SingleStore"},
    {"token": "yugabyte", "name": "Yugabyte"},
    {"token": "fastly", "name": "Fastly"},
    {"token": "circleci", "name": "CircleCI"},
    {"token": "buildkite", "name": "Buildkite"},
    # Security
    {"token": "chainguard", "name": "Chainguard"},
    {"token": "tines", "name": "Tines"},
    {"token": "torq", "name": "Torq"},
    {"token": "descope", "name": "Descope"},
    # Customer messaging / marketing infra
    {"token": "customerio", "name": "Customer.io"},
    {"token": "braze", "name": "Braze"},
    {"token": "iterable", "name": "Iterable"},
    {"token": "klaviyo", "name": "Klaviyo"},
    {"token": "attentive", "name": "Attentive"},
    {"token": "sendbird", "name": "Sendbird"},
    # Fintech / global (EU + LatAm)
    {"token": "adyen", "name": "Adyen"},
    {"token": "gocardless", "name": "GoCardless"},
    {"token": "sumup", "name": "SumUp"},
    {"token": "nubank", "name": "Nubank"},
    {"token": "quintoandar", "name": "QuintoAndar"},
    {"token": "ebanx", "name": "EBANX"},
    {"token": "c6bank", "name": "C6 Bank"},
    {"token": "stone", "name": "Stone"},
    {"token": "inter", "name": "Inter"},
    {"token": "gemini", "name": "Gemini"},
    {"token": "komodohealth", "name": "Komodo Health"},
]

# Role keywords for filtering
ROLE_KEYWORDS = [
    "software engineer", "backend engineer", "full stack", "full-stack",
    "frontend engineer", "platform engineer", "ai engineer", "ml engineer",
    "machine learning", "data engineer", "infrastructure engineer",
    "devops", "site reliability", "product engineer", "application engineer",
    "engineering intern", "software intern", "swe intern", "software developer",
    "agent engineer", "llm engineer",
]

JUNIOR_KEYWORDS = ["intern", "junior", "associate", "new grad", "entry level", "entry-level", "university", "campus"]
SENIOR_KEYWORDS = ["senior", "staff", "principal", " lead", "lead ", "director", " manager", " vp", "head of", "architect", "sr.", "sr ", "vp ", "distinguished", "fellow"]


async def scrape_greenhouse_board(
    client: httpx.AsyncClient,
    board_token: str,
    company_name: str,
    target_locations: list[str],
    min_salary_inr: int,
    max_age_days: int,
) -> list[JobListing]:
    """Scrape a single Greenhouse board for matching jobs."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    jobs: list[JobListing] = []

    try:
        resp = await client.get(url, params={"content": "true"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return jobs

    all_jobs = data.get("jobs", [])
    for job in all_jobs:
        title = job.get("title", "")
        title_lower = title.lower()

        # Filter by role type
        if not any(kw in title_lower for kw in ROLE_KEYWORDS):
            continue

        import re as _re
        # Keep any non-senior SWE role. Requiring the literal word "junior"/"intern" in the
        # title excluded almost every real posting; excluding senior titles is the right filter
        # for a new grad (the match-score gate + tailoring handle fit downstream).
        if any(s in title_lower for s in SENIOR_KEYWORDS):
            continue

        # Location
        location = job.get("location", {}).get("name", "")
        location_lower = location.lower()

        location_match = False
        for target in target_locations:
            if target.lower() in location_lower:
                location_match = True
                break
        if "remote" in location_lower or "india" in location_lower:
            location_match = True
        if not location_match:
            continue

        # Freshness
        posted_str = job.get("updated_at", "")
        posted_date = None
        if posted_str:
            try:
                posted_date = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        if posted_date:
            age = (datetime.now(timezone.utc) - posted_date).total_seconds() / 86400
            if age > max_age_days:
                continue

        # Build description from job content
        desc_parts = []
        for office in job.get("offices", []):
            for dept in office.get("departments", []):
                desc_parts.append(dept.get("name", ""))
        description = " | ".join(filter(None, desc_parts))

        job_id = f"gh-{board_token}-{title.lower().replace(' ', '-')[:40]}"
        absolute_url = job.get("absolute_url", "")

        jobs.append(JobListing(
            id=job_id,
            title=title,
            company=company_name,
            location=location,
            url=absolute_url,
            source="greenhouse",
            description=description,
            posted_date=posted_date,
            is_remote="remote" in location_lower,
            employment_type="internship" if "intern" in title_lower else "full-time",
            seniority="intern" if "intern" in title_lower else "junior",
            company_size="startup",
        ))

    return jobs


async def scrape_greenhouse_all(
    max_age_days: int = 4,
    min_salary_inr: int = 50_000,
    target_locations: Optional[list[str]] = None,
    max_concurrent: int = 10,
) -> list[JobListing]:
    """Scrape all configured Greenhouse boards concurrently."""
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    all_jobs: list[JobListing] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(board: dict):
        async with semaphore:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await scrape_greenhouse_board(
                    client,
                    board["token"],
                    board["name"],
                    target_locations,
                    min_salary_inr,
                    max_age_days,
                )

    tasks = [scrape_one(b) for b in GREENHOUSE_BOARDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job.id not in seen:
            seen.add(job.id)
            unique_jobs.append(job)

    return unique_jobs
