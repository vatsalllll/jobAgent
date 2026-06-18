"""
LinkedIn recruiter finder — uses Google search to find hiring managers and recruiters
at target companies, then drafts personalized connection messages.

Run locally:
    python -m outreach.linkedin_finder --company "Stripe" --role "Software Engineer Intern"
"""

import argparse
import asyncio
import json
import re

import httpx
from bs4 import BeautifulSoup


async def google_linkedin_search(company: str, role: str = "recruiter") -> list[dict]:
    """
    Search for LinkedIn profiles at a company using DuckDuckGo HTML
    (more reliable than Google scraping, no CAPTCHA).
    Returns list of {name, title, linkedin_url, snippet}
    """
    queries = [
        f'site:linkedin.com/in "{company}" "{role}"',
        f'site:linkedin.com/in "{company}" hiring',
        f'site:linkedin.com/in "{company}" talent',
        f'site:linkedin.com/in "{company}" engineering manager',
    ]

    results = []
    seen_urls = set()

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
    ) as client:
        for query in queries:
            try:
                url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                for result_div in soup.find_all("div", class_=re.compile(r"result", re.I)):
                    a = result_div.find("a", href=True)
                    if not a:
                        continue
                    href = a.get("href", "")
                    if "linkedin.com/in/" not in href and "uddg=" in href:
                        match = re.search(r"uddg=([^&]+)", href)
                        if match:
                            from urllib.parse import unquote
                            href = unquote(match.group(1))

                    if "linkedin.com/in/" not in href:
                        continue

                    profile_match = re.search(r"linkedin\.com/in/([a-zA-Z0-9-]+)", href)
                    if not profile_match:
                        continue
                    profile_url = f"https://linkedin.com/in/{profile_match.group(1)}"
                    if profile_url in seen_urls:
                        continue
                    seen_urls.add(profile_url)

                    name = a.get_text(strip=True)
                    snippet_el = result_div.find(class_=re.compile(r"snippet|result__snippet", re.I))
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                    if not name or len(name) < 3:
                        text = result_div.get_text(separator=" | ", strip=True)
                        name = text.split("|")[0].strip()[:60] if text else ""

                    results.append({
                        "name": name,
                        "title": snippet[:200],
                        "linkedin_url": profile_url,
                        "query_used": query,
                    })

                    if len(results) >= 10:
                        break

            except Exception:
                continue

            if len(results) >= 10:
                break

    return results[:5]


def draft_message(contact_name: str, company: str, role: str) -> str:
    """Draft a personalized LinkedIn connection message."""
    first_name = contact_name.split()[0] if contact_name else "there"
    return (
        f"Hi {first_name}, I'm Vatsal — a CS student at BITS Pilani with hands-on "
        f"experience in multi-agent AI systems (ChaosOps AI) and full-stack engineering "
        f"(internship at BLive, scaling to Zomato/TVS/Ather). I recently came across "
        f"a {role} opening at {company} and would love to learn more. Would you be "
        f"open to a quick chat? Always happy to share my tailored resume. 🙏"
    )


async def main():
    parser = argparse.ArgumentParser(description="Find recruiters on LinkedIn")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--role", default="Software Engineer Intern", help="Role title")
    parser.add_argument("--no-browser", action="store_true", help="Don't open in browser")
    args = parser.parse_args()

    print(f"🔍 Searching LinkedIn for recruiters at {args.company}...")
    contacts = await google_linkedin_search(args.company, args.role)

    if not contacts:
        print(f"❌ No LinkedIn profiles found for {args.company}")
        return

    print(f"\n✅ Found {len(contacts)} LinkedIn profiles:\n")
    for i, c in enumerate(contacts, 1):
        print(f"  {i}. {c['name'] or 'Unknown'}")
        print(f"     {c['title'][:100]}")
        print(f"     {c['linkedin_url']}")
        print()

    if not args.no_browser:
        try:
            from playwright.async_api import async_playwright
            print(f"\n🌐 Opening in browser...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()

                for c in contacts:
                    await page.goto(c["linkedin_url"], wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2000)

                    name = c["name"] or "there"
                    msg = draft_message(name, args.company, args.role)
                    print(f"\n📝 Drafted message for {name}:")
                    print(f"   {msg[:200]}...")
                    print(f"\n   Press Enter for next profile, 'q' to quit...")
                    choice = input("   → ").strip().lower()
                    if choice == "q":
                        break

                await browser.close()
        except ImportError:
            print("\n⚠️  Playwright not installed. Run: pip install playwright && playwright install chromium")


if __name__ == "__main__":
    asyncio.run(main())
