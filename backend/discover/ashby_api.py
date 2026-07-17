import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from discover.models import JobListing

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"

ASHBY_BOARDS = [
    "a-team",
    "retool",
    "linear",
    "ramp",
    "vanta",
    "mercury",
    "modal",
    "cursor",
    # Frontier AI / ML labs and infra (verified live 2026-07)
    "openai",
    "perplexity",
    "cognition",
    "harvey",
    "sierra",
    "decagon",
    "langchain",
    "llamaindex",
    "elevenlabs",
    "suno",
    "deepgram",
    "cartesia",
    "synthesia",
    "runway",
    "pika",
    "viggle",
    "tavus",
    "rime",
    "character",
    "cerebras",
    "crusoe",
    "etched",
    "d-matrix",
    "rain",
    "baseten",
    "replit",
    "pinecone",
    "weaviate",
    # Product / infra scaleups
    "notion",
    "posthog",
    "watershed",
    "vapi",
    "bland",
    "gorgias",
    "pylon",
    "plain",
    "crisp",
    "lorikeet",
    # India-based / India-hiring
    "atlan",
    "navi",
    "sarvam",
]


async def scrape_ashby_board(client: httpx.AsyncClient, board: str, target_locations: list[str]) -> list[JobListing]:
    url = f"{ASHBY_API}/{board}"
    jobs = []

    try:
        resp = await client.get(url, timeout=20.0)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
    except Exception:
        return jobs

    for j in data.get("jobs", []):
        title = j.get("title", "")
        if not title:
            continue

        title_lower = title.lower()
        location = j.get("location", "")
        location_lower = location.lower() if location else ""

        is_software = any(kw in title_lower for kw in [
            "software", "engineer", "developer", "full stack", "fullstack", "frontend",
            "backend", "ai", "ml", "data", "platform", "devops", "sre", "agent",
            "ops", "technical", "tech", "architect",
        ])
        if not is_software:
            continue

        is_remote = "remote" in location_lower or "anywhere" in location_lower or "worldwide" in location_lower

        if not is_remote:
            if not any(t.lower() in location_lower for t in target_locations):
                continue

        # Keep any non-senior SWE role (requiring the literal word "junior" starved results).
        if any(s in title_lower for s in ["senior", "staff", "principal", " lead", "lead ", "director", "head of", " manager", " vp", "architect", "sr.", "sr ", "distinguished"]):
            continue

        seniority = "intern" if "intern" in title_lower else "junior"

        apply_url = j.get("applyUrl") or j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}"

        jobs.append(JobListing(
            id=f"ashby-{board}-{title.lower().replace(' ', '-')[:40]}",
            title=title,
            company=board.title(),
            location=location or "Remote",
            url=apply_url,
            source="ashby",
            description=j.get("description", "")[:500],
            posted_date=datetime.now(timezone.utc),
            is_remote=is_remote,
            employment_type="full-time",
            seniority=seniority,
            company_size="startup",
        ))

    return jobs


async def scrape_ashby_all(
    target_locations: Optional[list[str]] = None,
    max_concurrent: int = 5,
) -> list[JobListing]:
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    all_jobs = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_one(board: str):
        async with semaphore:
            async with httpx.AsyncClient(timeout=20.0) as client:
                return await scrape_ashby_board(client, board, target_locations)

    tasks = [scrape_one(b) for b in ASHBY_BOARDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)

    seen = set()
    unique = []
    for j in all_jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)

    return unique
