"""
YC Work at a Startup job scraper using Playwright.
The site is fully JS-rendered (React). Job entries and company links
appear in the same order in the DOM — we pair them by position.

Set DISABLE_PLAYWRIGHT=true to skip this scraper (for cloud deployments).
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional

from discover.models import JobListing

YC_BASE = "https://www.workatastartup.com"

ROLE_KEYWORDS = [
    "software engineer", "backend engineer", "full stack", "full-stack",
    "frontend engineer", "platform engineer", "ai engineer", "ml engineer",
    "machine learning", "data engineer", "infrastructure engineer",
    "devops", "site reliability", "product engineer", "application engineer",
    "engineering intern", "software intern", "swe intern", "software developer",
    "agent engineer", "llm engineer", "founding engineer",
]

JUNIOR_KEYWORDS = [
    "intern", "junior", "associate", "new grad", "entry level", "entry-level",
    "university", "campus", "graduate",
]

SENIOR_KEYWORDS = [
    "senior", "staff", "principal", "lead,", "director", "head of",
    "manager", "vp", "architect", "distinguished",
]


async def scrape_yc_jobs(
    max_age_days: int = 4,
    min_salary_inr: int = 50_000,
    target_locations: Optional[list[str]] = None,
) -> list[JobListing]:
    """
    Scrape YC Work at a Startup for entry-level/junior SWE roles.
    Uses Playwright since the site is fully JS-rendered.
    """
    if target_locations is None:
        target_locations = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram", "India"]

    if os.getenv("DISABLE_PLAYWRIGHT", "").lower() == "true":
        from discover.yc_api_fallback import scrape_yc_api_fallback
        return await scrape_yc_api_fallback(
            max_age_days=max_age_days,
            min_salary_inr=min_salary_inr,
            target_locations=target_locations,
        )

    from playwright.async_api import async_playwright

    jobs: list[JobListing] = []
    now = datetime.now(timezone.utc)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        url = f"{YC_BASE}/jobs?role=software-engineer"
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(4000)
        except Exception:
            await browser.close()
            return jobs

        raw_jobs = await page.evaluate("""
            () => {
                const companyLinks = Array.from(
                    document.querySelectorAll('a[href*="/companies/"]')
                ).map(a => {
                    const text = a.textContent.trim();
                    const name = text.split('•')[0].trim().replace(/\u00A0/g, ' ');
                    const description = text.split('•').slice(1).join('•').trim();
                    return { name, description, url: a.href };
                });

                const jobEntries = Array.from(
                    document.querySelectorAll('[class*="job"]')
                ).map(entry => {
                    const spans = Array.from(entry.querySelectorAll('span'))
                        .map(s => s.textContent.trim())
                        .filter(Boolean);
                    const link = entry.closest('a');
                    const jobUrl = link ? link.href : '';
                    return { spans, url: jobUrl };
                });

                const paired = [];
                const minLen = Math.min(companyLinks.length, jobEntries.length);
                for (let i = 0; i < minLen; i++) {
                    paired.push({ company: companyLinks[i], job: jobEntries[i] });
                }
                return paired;
            }
        """)

        for item in raw_jobs:
            try:
                company_data = item.get("company", {})
                job_data = item.get("job", {})
                spans = job_data.get("spans", [])
                company_name = company_data.get("name", "")
                company_desc = company_data.get("description", "")

                if not company_name or len(spans) < 2:
                    continue

                employment_type = spans[0] if len(spans) > 0 else ""
                location = spans[1] if len(spans) > 1 else ""
                title = spans[2] if len(spans) > 2 else ""
                salary_text = spans[3] if len(spans) > 3 else ""

                if not title:
                    continue

                title_lower = title.lower()

                if not any(kw in title_lower for kw in ROLE_KEYWORDS):
                    continue
                if any(kw in title_lower for kw in SENIOR_KEYWORDS):
                    continue

                is_junior = any(kw in title_lower for kw in JUNIOR_KEYWORDS) or "intern" in employment_type.lower()
                is_generic = title_lower in ["full stack", "backend", "frontend", "software engineer", "software developer"]
                if not is_junior and not is_generic:
                    continue

                location_lower = location.lower()
                loc_match = any(t.lower() in location_lower for t in target_locations) or "remote" in location_lower or "india" in location_lower
                if not loc_match:
                    continue

                salary_min = _extract_salary(salary_text) if salary_text else None
                if min_salary_inr > 0 and salary_min is not None and salary_min < min_salary_inr:
                    continue

                job_url = job_data.get("url", "")
                if not job_url:
                    job_url = f"{YC_BASE}/companies/{company_name.lower().replace(' ', '-')}/jobs"

                job_id = f"yc-{company_name.lower().replace(' ', '-')}-{title.lower().replace(' ', '-')[:40]}"

                jobs.append(JobListing(
                    id=job_id,
                    title=title,
                    company=company_name,
                    location=location,
                    url=job_url,
                    source="yc",
                    description=company_desc,
                    salary_min=salary_min,
                    salary_currency=_guess_currency(salary_text),
                    posted_date=now,
                    is_remote="remote" in location_lower,
                    employment_type="internship" if "intern" in employment_type.lower() else "full-time",
                    seniority="intern" if "intern" in title_lower else "junior",
                    company_size="startup",
                ))
            except Exception:
                continue

        await browser.close()

    seen = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique


def _extract_salary(text: str) -> Optional[float]:
    text = text.replace(",", "").strip()
    # USD
    m = re.search(r"\$\s*(\d[\d.]*)\s*[kK]?", text)
    if m:
        v = float(m.group(1))
        if "k" in text.lower() or v < 1000:
            v *= 1000
        return v * 83 / 12
    # INR
    m = re.search(r"[₹]\s*(\d[\d,.]*)", text)
    if m:
        v = float(m.group(1).replace(",", ""))
        return v / 12 if v > 100000 else v
    # EUR
    m = re.search(r"€\s*(\d[\d,.]*)\s*[kK]?", text)
    if m:
        v = float(m.group(1).replace(",", ""))
        if "k" in text.lower() or v < 1000:
            v *= 1000
        return v * 90 / 12
    return None


def _guess_currency(text: str) -> str:
    if "₹" in text: return "INR"
    if "$" in text: return "USD"
    if "€" in text: return "EUR"
    return "USD"
