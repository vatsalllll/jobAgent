"""Greenhouse job application auto-fill using Playwright.

Fills out Greenhouse application forms automatically:
  - Personal info (name, email, phone, location)
  - Resume upload (PDF)
  - Cover letter (pasted text)
  - Basic questions (yes/no, short text, dropdowns)

The script navigates to a Greenhouse job URL, detects form fields,
and fills them using data from the base resume.

IMPORTANT: This requires Playwright browsers to be installed:
  python -m playwright install chromium
"""

import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page

from data.base_resume import BASE_RESUME
from config import settings

logger = logging.getLogger(__name__)

# Mapping of common Greenhouse field labels to resume keys
FIELD_MAPPINGS = {
    # Name fields
    "first name": "first_name",
    "firstname": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "full name": "full_name",
    "name": "full_name",
    # Contact fields
    "email": "email",
    "e-mail": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "linkedin": "linkedin",
    "linkedin profile": "linkedin",
    "linkedin url": "linkedin",
    "website": "website",
    "portfolio": "website",
    "portfolio url": "website",
    "github": "github",
    "github url": "github",
    # Location fields
    "location": "location",
    "city": "city",
    "country": "country",
    "current location": "location",
    # Work authorization
    "work authorization": "work_auth",
    "authorized to work": "work_auth",
    "sponsorship": "sponsorship",
    "require sponsorship": "sponsorship",
    # Education
    "school": "school",
    "university": "school",
    "degree": "degree",
    # Cover letter
    "cover letter": "cover_letter",
    "why do you want": "cover_letter",
    "tell us about yourself": "cover_letter",
    # Generic
    "how did you hear": "referral",
    "referral": "referral",
    "source": "referral",
}


def _get_resume_value(key: str) -> str:
    """Extract a value from BASE_RESUME for form filling."""
    basics = BASE_RESUME.get("basics", {})

    if key == "first_name":
        return basics.get("name", "").split()[0] if basics.get("name") else ""
    if key == "last_name":
        parts = basics.get("name", "").split()
        return parts[-1] if len(parts) > 1 else ""
    if key == "full_name":
        return basics.get("name", "")
    if key == "email":
        return basics.get("email", settings.sender_email)
    if key == "phone":
        return basics.get("phone", "")
    if key == "linkedin":
        for p in basics.get("profiles", []):
            if p.get("network", "").lower() == "linkedin":
                return p.get("url", "")
        return ""
    if key == "github":
        for p in basics.get("profiles", []):
            if p.get("network", "").lower() == "github":
                return p.get("url", "")
        return ""
    if key == "website":
        return basics.get("url", "")
    if key == "location":
        loc = basics.get("location", {})
        return f"{loc.get('city', '')}, {loc.get('region', '')}, {loc.get('countryCode', '')}"
    if key == "city":
        return basics.get("location", {}).get("city", "")
    if key == "country":
        return basics.get("location", {}).get("countryCode", "")
    if key == "school":
        edu = BASE_RESUME.get("education", [])
        return edu[0].get("institution", "") if edu else ""
    if key == "degree":
        edu = BASE_RESUME.get("education", [])
        return f"{edu[0].get('studyType', '')} in {edu[0].get('area', '')}" if edu else ""
    if key == "work_auth":
        return "Yes"  # Default for Indian citizens applying to remote roles
    if key == "sponsorship":
        return "No"  # Most applicants don't need sponsorship for remote
    if key == "cover_letter":
        return (
            f"Hi, I'm {basics.get('name', 'a software engineer')} — a CS student at BITS Pilani "
            f"graduating in 2026. I have hands-on experience building production multi-agent systems, "
            f"LLM orchestration pipelines, and real-time IoT platforms. I'm excited about this role "
            f"because it aligns with my background in AI agents and distributed systems."
        )
    if key == "referral":
        return "LinkedIn"

    return ""


async def _fill_text_field(page: Page, label_text: str, value: str) -> bool:
    """Find a text input by its associated label and fill it."""
    if not value:
        return False
    try:
        # Strategy 1: Find label containing text, then find associated input
        label_locator = page.locator(f"label:has-text('{label_text}')")
        if await label_locator.count() > 0:
            # Try to find input by 'for' attribute or proximity
            input_id = await label_locator.get_attribute("for")
            if input_id:
                input_field = page.locator(f"#{input_id}")
                if await input_field.count() > 0:
                    await input_field.fill(value)
                    return True

        # Strategy 2: Find input with placeholder matching label
        placeholder_input = page.locator(f"input[placeholder*='{label_text}' i], textarea[placeholder*='{label_text}' i]")
        if await placeholder_input.count() > 0:
            await placeholder_input.first.fill(value)
            return True

        # Strategy 3: Find input by aria-label
        aria_input = page.locator(f"[aria-label*='{label_text}' i]")
        if await aria_input.count() > 0:
            await aria_input.first.fill(value)
            return True

        return False
    except Exception as e:
        logger.warning(f"Failed to fill field '{label_text}': {e}")
        return False


async def _upload_resume(page: Page, pdf_path: str) -> bool:
    """Upload resume PDF to Greenhouse file input."""
    if not pdf_path or not Path(pdf_path).exists():
        logger.warning(f"PDF not found: {pdf_path}")
        return False

    try:
        # Greenhouse resume upload is typically an input[type="file"]
        file_input = page.locator("input[type='file']").first
        if await file_input.count() > 0:
            await file_input.set_input_files(pdf_path)
            logger.info(f"Uploaded resume: {pdf_path}")
            return True

        # Alternative: look for resume-specific upload
        resume_upload = page.locator("[data-field='resume'] input[type='file']").first
        if await resume_upload.count() > 0:
            await resume_upload.set_input_files(pdf_path)
            logger.info(f"Uploaded resume via data-field: {pdf_path}")
            return True

        return False
    except Exception as e:
        logger.warning(f"Resume upload failed: {e}")
        return False


async def _answer_dropdown(page: Page, question_text: str, answer: str) -> bool:
    """Answer a dropdown/select question."""
    try:
        # Find select near the question text
        select_locator = page.locator(f"select", has=page.locator(f"option:has-text('{answer}')"))
        if await select_locator.count() == 0:
            # Try finding by label proximity
            label = page.locator(f"label:has-text('{question_text}')")
            if await label.count() > 0:
                select_id = await label.get_attribute("for")
                if select_id:
                    select_locator = page.locator(f"#{select_id}")

        if await select_locator.count() > 0:
            await select_locator.first.select_option(answer)
            return True

        return False
    except Exception as e:
        logger.warning(f"Dropdown answer failed for '{question_text}': {e}")
        return False


async def _answer_yes_no(page: Page, question_text: str, answer_yes: bool) -> bool:
    """Answer a yes/no radio button question."""
    try:
        # Find the question container
        container = page.locator(f"div:has-text('{question_text}')")
        if await container.count() == 0:
            return False

        # Look for radio buttons within the container
        radios = container.first.locator("input[type='radio']")
        if await radios.count() == 0:
            return False

        # Click the appropriate option (first for yes, second for no usually)
        index = 0 if answer_yes else 1
        if await radios.count() > index:
            await radios.nth(index).check()
            return True

        return False
    except Exception as e:
        logger.warning(f"Yes/No answer failed for '{question_text}': {e}")
        return False


async def _detect_and_fill_questions(page: Page) -> dict[str, bool]:
    """Detect all question fields on the page and fill them."""
    results = {}

    # Iterate through known field mappings
    for label_text, resume_key in FIELD_MAPPINGS.items():
        value = _get_resume_value(resume_key)
        if value:
            success = await _fill_text_field(page, label_text, value)
            if success:
                results[label_text] = True

    return results


async def auto_apply_greenhouse(
    job_url: str,
    pdf_path: Optional[str] = None,
    headless: bool = True,
    dry_run: bool = True,
) -> dict:
    """Auto-fill a Greenhouse job application form.

    Args:
        job_url: The Greenhouse job application URL
        pdf_path: Path to the tailored resume PDF (optional)
        headless: Run browser in headless mode
        dry_run: If True, fills the form but does NOT click submit.
                 Set to False only when you are ready to actually apply.

    Returns:
        dict with:
            - success: bool
            - fields_filled: int
            - resume_uploaded: bool
            - submitted: bool
            - url: str
            - screenshot: Optional[str] — path to form screenshot
    """
    fields_filled = 0
    resume_uploaded = False
    screenshot_path = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})

            logger.info(f"Navigating to {job_url}")
            await page.goto(job_url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2000)

            # Check if we're on an application form
            if await page.locator("#application-form").count() == 0 and \
               await page.locator("[data-messages='ApplicantForm']").count() == 0 and \
               await page.locator("input[type='file']").count() == 0:
                logger.warning(f"No application form detected at {job_url}")
                await browser.close()
                return {
                    "success": False,
                    "fields_filled": 0,
                    "resume_uploaded": False,
                    "submitted": False,
                    "url": job_url,
                    "screenshot": None,
                    "error": "No application form found",
                }

            # Fill detected fields
            filled = await _detect_and_fill_questions(page)
            fields_filled = len(filled)
            logger.info(f"Filled {fields_filled} fields on {job_url}")

            # Upload resume if available
            if pdf_path:
                resume_uploaded = await _upload_resume(page, pdf_path)

            # Additional: fill cover letter textarea if present
            cover_letter = _get_resume_value("cover_letter")
            try:
                textarea = page.locator("textarea#cover_letter, textarea[name*='cover'], textarea[placeholder*='cover' i]")
                if await textarea.count() > 0:
                    await textarea.first.fill(cover_letter)
                    fields_filled += 1
            except Exception:
                pass

            # Take screenshot before submission (or after if dry run)
            screenshot_path = str(Path(settings.output_dir) / f"greenhouse_{Path(job_url).name}.png")
            await page.screenshot(path=screenshot_path, full_page=True)

            submitted = False
            if not dry_run:
                # Click submit button
                submit_btn = page.locator("input[type='submit'], button[type='submit']").first
                if await submit_btn.count() > 0:
                    await submit_btn.click()
                    await page.wait_for_timeout(3000)
                    submitted = True
                    logger.info(f"Submitted application to {job_url}")

                    # Post-submit screenshot
                    screenshot_path = str(Path(settings.output_dir) / f"greenhouse_{Path(job_url).name}_submitted.png")
                    await page.screenshot(path=screenshot_path, full_page=True)
                else:
                    logger.warning("No submit button found")

            await browser.close()

            return {
                "success": True,
                "fields_filled": fields_filled,
                "resume_uploaded": resume_uploaded,
                "submitted": submitted,
                "url": job_url,
                "screenshot": screenshot_path,
                "dry_run": dry_run,
            }

    except Exception as e:
        logger.error(f"Greenhouse auto-apply failed for {job_url}: {e}")
        return {
            "success": False,
            "fields_filled": fields_filled,
            "resume_uploaded": resume_uploaded,
            "submitted": False,
            "url": job_url,
            "screenshot": screenshot_path,
            "error": str(e),
        }
