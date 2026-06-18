"""
Toptal job scraper — uses Playwright since Toptal blocks direct HTTP requests.
Works locally only (Playwright not available on Render free tier).

Run locally:
    python -m discover.toptal_scraper
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

from discover.models import JobListing

TOPTAL_BASE = "https://www.toptal.com"


async def scrape_toptal(
    max_age_days: int = 4,
    target_locations: Optional[list[str]] = None,
) -> list[JobListing]:
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    jobs = []
    now = datetime.now(timezone.utc)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(f"{TOPTAL_BASE}/jobs", wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)

            raw = await page.evaluate("""
                () => {
                    const jobs = [];
                    const cards = document.querySelectorAll('[class*="job"], [class*="opportunity"], [class*="gig"], [class*="project"]');
                    cards.forEach(card => {
                        const titleEl = card.querySelector('h2, h3, h4, [class*="title"]');
                        const companyEl = card.querySelector('[class*="company"], [class*="client"]');
                        const linkEl = card.querySelector('a[href]');
                        if (titleEl) {
                            jobs.push({
                                title: titleEl.textContent.trim(),
                                company: companyEl ? companyEl.textContent.trim() : '',
                                url: linkEl ? linkEl.href : '',
                                text: card.textContent.trim().slice(0, 500)
                            });
                        }
                    });
                    return jobs;
                }
            """)

            for item in raw[:20]:
                title = item.get("title", "")
                if not title:
                    continue
                title_lower = title.lower()
                if not any(kw in title_lower for kw in [
                    "engineer", "developer", "full stack", "frontend", "backend",
                    "ai", "ml", "data", "platform", "devops", "agent"
                ]):
                    continue

                is_remote = "remote" in item.get("text", "").lower() or not item.get("company")

                if not is_remote and target_locations:
                    if not any(t.lower() in item.get("text", "").lower() for t in target_locations):
                        continue

                jobs.append(JobListing(
                    id=f"toptal-{title.lower().replace(' ', '-')[:40]}-{len(jobs)}",
                    title=title,
                    company=item.get("company") or "Toptal Client",
                    location="Remote",
                    url=item.get("url") or f"{TOPTAL_BASE}/jobs",
                    source="toptal",
                    posted_date=now,
                    is_remote=is_remote,
                    employment_type="contract",
                    seniority="mid",
                    company_size="freelance",
                ))
        except Exception as e:
            pass
        finally:
            await browser.close()

    return jobs
