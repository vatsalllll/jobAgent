import asyncio
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from discover.models import JobListing


WWR_RSS = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
REMOTIVE_API = "https://remotive.com/api/remote-jobs"


async def scrape_weworkremotely(max_age_days: int = 14, target_locations: Optional[list[str]] = None) -> list[JobListing]:
    if target_locations is None:
        target_locations = ["Remote", "Worldwide", "Anywhere"]

    jobs = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(WWR_RSS, follow_redirects=True)
            if resp.status_code != 200:
                return jobs
            feed = feedparser.parse(resp.text)
        except Exception:
            return jobs

        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = entry.get("published_parsed")

            if not title:
                continue

            title_lower = title.lower()
            is_software = any(kw in title_lower for kw in [
                "engineer", "developer", "full stack", "fullstack", "frontend",
                "backend", "ai", "ml", "data", "platform", "devops", "sre",
                "agent", "software", "mobile", "ios", "android", "web",
                "programmer", "coding",
            ])
            if not is_software:
                continue

            is_junior = any(kw in title_lower for kw in [
                "intern", "junior", "associate", "new grad", "entry level", "entry-level", "university", "campus", "graduate", "apprentice", "co-op", "coop", "trainee", "fresher"
            ]) and not any(s in title_lower for s in ["senior", "staff", "principal", "lead", "director", "head of", "manager", "vp", "architect", "sr.", "sr "])
            if not is_junior:
                continue

            posted = now
            if published:
                try:
                    posted = datetime(*published[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            age = (now - posted).total_seconds() / 86400
            if age > 30:
                continue

            company = "Unknown"
            if ": " in title and title.split(": ")[0].count(" ") < 5:
                company = title.split(": ")[0].strip()
            elif " at " in title:
                parts = title.split(" at ", 1)
                if len(parts) == 2:
                    company = parts[1].strip().split(":")[0].strip()

            jobs.append(JobListing(
                id=f"wwr-{link.split('/')[-1] if link else title.lower().replace(' ', '-')[:40]}",
                title=title,
                company=company,
                location="Remote",
                url=link,
                source="weworkremotely",
                description=summary[:500] if summary else "",
                posted_date=posted,
                is_remote=True,
                employment_type="full-time",
                seniority="mid",
                company_size="remote",
            ))

    return jobs


async def scrape_remotive(target_categories: Optional[list[str]] = None) -> list[JobListing]:
    if target_categories is None:
        target_categories = ["software-dev", "software development", "data", "devops-sysadmin", "engineering"]

    jobs = []
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(REMOTIVE_API, params={"limit": 50})
            if resp.status_code != 200:
                return jobs
            data = resp.json()
        except Exception:
            return jobs

        jobs_data = data.get("jobs", [])

        for j in jobs_data:
            category = j.get("category", "")
            category_lower = category.lower().replace(" ", "-")
            if not any(c.lower() in category_lower for c in target_categories):
                continue

            title = j.get("title", "")
            company = j.get("company_name", "")
            url = j.get("url", "")
            job_type = j.get("job_type", "")
            publication_date = j.get("publication_date", "")

            if not title or not company:
                continue

            title_lower = title.lower()
            is_software = any(kw in title_lower for kw in [
                "engineer", "developer", "full stack", "fullstack", "frontend",
                "backend", "ai", "ml", "data", "platform", "devops", "sre",
                "agent", "software", "mobile", "ios", "android", "web",
            ])
            if not is_software:
                continue

            is_junior = any(kw in title_lower for kw in [
                "intern", "junior", "associate", "new grad", "entry level", "entry-level", "university", "campus", "graduate", "apprentice", "co-op", "coop", "trainee", "fresher"
            ]) and not any(s in title_lower for s in ["senior", "staff", "principal", "lead", "director", "head of", "manager", "vp", "architect", "sr.", "sr "])
            if not is_junior:
                continue

            posted = now
            if publication_date:
                try:
                    parsed = datetime.fromisoformat(publication_date.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    posted = parsed
                except Exception:
                    pass

            age = (now - posted).total_seconds() / 86400
            if age > 30:
                continue

            jobs.append(JobListing(
                id=f"remotive-{j.get('id', '')}",
                title=title,
                company=company,
                location="Remote",
                url=url,
                source="remotive",
                description=j.get("description", "")[:500],
                posted_date=posted,
                is_remote=True,
                employment_type="full-time" if "full" in job_type.lower() else job_type,
                seniority="mid",
                company_size="remote",
            ))

    return jobs
