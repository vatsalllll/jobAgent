import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

from discover.models import JobListing


UPWORK_RSS = "https://www.upwork.com/ab/feed/jobs/rss?q=software+engineer&sort=recency"
TURING_SEARCH = "https://www.turing.com/api/v1/jobs/search"


async def scrape_upwork_rss(target_keywords: Optional[list[str]] = None) -> list[JobListing]:
    if target_keywords is None:
        target_keywords = ["python", "typescript", "react", "node", "ai", "llm", "agent", "backend", "fullstack", "software"]

    jobs = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    ) as client:
        try:
            resp = await client.get(UPWORK_RSS, follow_redirects=True)
            if resp.status_code != 200:
                return jobs
            feed = feedparser.parse(resp.text)
        except Exception:
            return jobs

        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = entry.get("published_parsed")

            title_lower = title.lower()
            summary_lower = summary.lower() if summary else ""

            if not any(kw.lower() in title_lower or kw.lower() in summary_lower for kw in target_keywords):
                continue

            posted = now
            if published:
                try:
                    posted = datetime(*published[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            age = (now - posted).total_seconds() / 86400
            if age > 4:
                continue

            jobs.append(JobListing(
                id=f"upwork-{link.split('~')[-1] if '~' in link else link.split('/')[-1]}",
                title=title,
                company="Upwork Client",
                location="Remote",
                url=link,
                source="upwork",
                description=summary[:500] if summary else "",
                posted_date=posted,
                is_remote=True,
                employment_type="contract",
                seniority="mid",
                company_size="freelance",
            ))

    return jobs


async def scrape_turing(target_keywords: Optional[list[str]] = None) -> list[JobListing]:
    """Turing job board — uses their public-facing search API."""
    if target_keywords is None:
        target_keywords = ["python", "typescript", "react", "node", "ai", "llm", "agent", "fullstack", "backend"]

    jobs = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    ) as client:
        for keyword in target_keywords[:3]:
            try:
                resp = await client.post(
                    TURING_SEARCH,
                    json={"keyword": keyword, "page": 0, "limit": 10},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
            except Exception:
                continue

            items = data.get("results", data.get("jobs", []))
            if not isinstance(items, list):
                continue

            for item in items:
                title = item.get("title") or item.get("name", "")
                company = item.get("company") or "Turing Client"
                url = item.get("url") or item.get("link", "https://www.turing.com/jobs")
                desc = item.get("description", "")

                if not title:
                    continue

                jobs.append(JobListing(
                    id=f"turing-{item.get('id', '')}{keyword}",
                    title=title,
                    company=company,
                    location="Remote",
                    url=url,
                    source="turing",
                    description=desc[:500] if desc else "",
                    posted_date=now,
                    is_remote=True,
                    employment_type="contract",
                    seniority="mid",
                    company_size="freelance",
                ))

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique[:20]
