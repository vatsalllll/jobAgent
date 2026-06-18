"""
Local auto-apply script — uses Playwright to fill out Greenhouse, Lever, and Workday forms.

Run from your Mac:
    cd ~/job-agent/backend
    source venv/bin/activate
    python -m outreach.auto_apply

It reads jobs from the tracker, opens each application URL in Chromium,
fills the form with your resume data, and pauses for your review before
submitting. You stay in control — nothing is submitted without your Enter.
"""

import sys
import time
from pathlib import Path

from tracker import _get_db, update_status


def list_pending() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM applications WHERE status IN ('tailored', 'ready_to_apply') AND url != '' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_ats(url: str) -> str:
    u = url.lower()
    if "greenhouse" in u or "boards.greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u or "jobs.lever" in u:
        return "lever"
    if "myworkdayjobs" in u:
        return "workday"
    if "linkedin.com/jobs" in u:
        return "linkedin"
    if "wellfound" in u or "angel.co" in u:
        return "wellfound"
    if "workatastartup" in u:
        return "yc"
    return "unknown"


async def apply_to_greenhouse(page, job: dict, resume_data: dict) -> bool:
    try:
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        full_name = resume_data["basics"]["name"]
        email = resume_data["basics"]["email"]
        phone = resume_data["basics"]["phone"]
        location = f"{resume_data['basics']['location']['city']}, {resume_data['basics']['location']['countryCode']}"

        fields = {
            "name": [full_name, "name", "full_name", "candidate_name"],
            "email": [email, "email_address", "applicant_email"],
            "phone": [phone, "phone_number", "mobile"],
            "location": [location, "current_location", "address"],
        }

        for field_type, possible_names in fields.items():
            for name in possible_names:
                el = await page.query_selector(f'input[name*="{name}" i]')
                if el:
                    await el.fill(fields[field_type][0])
                    break

        resume_input = await page.query_selector('input[type="file"]')
        if resume_input and job.get("resume_pdf"):
            pdf_path = Path(__file__).parent.parent / job["resume_pdf"]
            if pdf_path.exists():
                await resume_input.set_input_files(str(pdf_path))

        print(f"   ✅ Form filled for {job['company']} — {job['role']}")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def apply_to_lever(page, job: dict, resume_data: dict) -> bool:
    try:
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        full_name = resume_data["basics"]["name"]
        email = resume_data["basics"]["email"]
        phone = resume_data["basics"]["phone"]

        name_field = await page.query_selector('input[name*="name" i]')
        if name_field:
            await name_field.fill(full_name)
        email_field = await page.query_selector('input[name*="email" i]')
        if email_field:
            await email_field.fill(email)
        phone_field = await page.query_selector('input[name*="phone" i]')
        if phone_field:
            await phone_field.fill(phone)

        resume_input = await page.query_selector('input[type="file"]')
        if resume_input and job.get("resume_pdf"):
            pdf_path = Path(__file__).parent.parent / job["resume_pdf"]
            if pdf_path.exists():
                await resume_input.set_input_files(str(pdf_path))

        print(f"   ✅ Lever form filled for {job['company']}")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def apply_to_workday(page, job: dict, resume_data: dict) -> bool:
    print(f"   ⚠️  Workday: multi-step wizard — manual review required")
    try:
        await page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def main():
    from playwright.async_api import async_playwright
    import json

    base_resume_path = Path(__file__).parent.parent / "data" / "base_resume.py"
    if not base_resume_path.exists():
        print("❌ base_resume.py not found")
        return

    sys.path.insert(0, str(base_resume_path.parent.parent))
    from data.base_resume import BASE_RESUME

    jobs = list_pending()
    if not jobs:
        print("✅ No pending applications in tracker.")
        return

    print(f"📋 Found {len(jobs)} pending application(s):\n")
    for j in jobs:
        ats = detect_ats(j.get("url", ""))
        print(f"   [{ats.upper():10s}] {j['company'][:25]} — {j['role'][:40]}")

    print(f"\nPress Enter to open all in browser, or Ctrl+C to cancel...")
    input()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context()
        page = await context.new_page()

        for job in jobs:
            ats = detect_ats(job["url"])
            print(f"\n🌐 Opening: {job['company']} — {job['role']}")
            print(f"   URL: {job['url']}")
            print(f"   ATS: {ats}")

            if ats == "greenhouse":
                success = await apply_to_greenhouse(page, job, BASE_RESUME)
            elif ats == "lever":
                success = await apply_to_lever(page, job, BASE_RESUME)
            elif ats == "workday":
                success = await apply_to_workday(page, job, BASE_RESUME)
            else:
                print(f"   ⚠️  No auto-filler for {ats} — opened manually")
                await page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
                success = False

            print(f"\n   👀 Review the form in the browser.")
            print(f"   Press Enter to SUBMIT and continue, 's' to skip, 'q' to quit.")

            choice = input("   → ").strip().lower()

            if choice == "q":
                break
            elif choice == "s":
                update_status(job["id"], "skipped", notes="Skipped during auto-apply")
                continue
            else:
                submit_btn = await page.query_selector('button[type="submit"], input[type="submit"]')
                if submit_btn:
                    await submit_btn.click()
                    print(f"   ✅ Submitted {job['company']}!")
                    update_status(job["id"], "applied", notes=f"Auto-applied via {ats}")
                    await page.wait_for_timeout(3000)
                else:
                    print(f"   ⚠️  No submit button found — manual submission needed")
                    update_status(job["id"], "needs_manual_review")

        await browser.close()
        print("\n✅ Done! Check your tracker for updated statuses.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
