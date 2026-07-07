"""Tests for outreach/greenhouse_apply.py — Greenhouse auto-apply Playwright script.

Tests focus on:
  - Resume value extraction from BASE_RESUME
  - Field detection logic
  - URL validation
  - Dry-run safety

We mock Playwright browser interactions to avoid needing real Greenhouse forms.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from outreach.greenhouse_apply import (
    _get_resume_value,
    FIELD_MAPPINGS,
    auto_apply_greenhouse,
)


def _make_mock_locator(count_value: int = 0):
    """Create a mock Playwright locator with async methods."""
    mock = AsyncMock()
    mock.count = AsyncMock(return_value=count_value)
    mock.fill = AsyncMock()
    mock.first = mock  # self-referential for chaining
    mock.nth = AsyncMock(return_value=mock)
    mock.check = AsyncMock()
    mock.get_attribute = AsyncMock(return_value=None)
    mock.select_option = AsyncMock()
    mock.set_input_files = AsyncMock()
    return mock


def _make_mock_page(form_detected: bool = True):
    """Create a mock Playwright page with locator support."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()

    # Default locator returns a mock with count=0
    default_locator = _make_mock_locator(count_value=0)

    def _locator_side_effect(selector):
        # Form detection selectors
        if form_detected and any(s in selector for s in ["#application-form", "data-messages", "input[type='file']"]):
            return _make_mock_locator(count_value=1)
        return default_locator

    mock_page.locator = MagicMock(side_effect=_locator_side_effect)
    return mock_page


class TestGetResumeValue:
    def test_first_name(self):
        val = _get_resume_value("first_name")
        assert val == "Vatsal"

    def test_last_name(self):
        val = _get_resume_value("last_name")
        assert val == "Omar"

    def test_full_name(self):
        val = _get_resume_value("full_name")
        assert val == "Vatsal Omar"

    def test_email(self):
        val = _get_resume_value("email")
        assert "@" in val

    def test_phone(self):
        val = _get_resume_value("phone")
        assert val != ""

    def test_linkedin(self):
        val = _get_resume_value("linkedin")
        assert "linkedin.com" in val.lower()

    def test_github(self):
        val = _get_resume_value("github")
        assert "github.com" in val.lower()

    def test_location(self):
        val = _get_resume_value("location")
        assert "Bangalore" in val or "Karnataka" in val

    def test_school(self):
        val = _get_resume_value("school")
        assert "BITS" in val or "Pilani" in val

    def test_degree(self):
        val = _get_resume_value("degree")
        assert "Computer Science" in val

    def test_work_auth(self):
        val = _get_resume_value("work_auth")
        assert val == "Yes"

    def test_sponsorship(self):
        val = _get_resume_value("sponsorship")
        assert val == "No"

    def test_cover_letter(self):
        val = _get_resume_value("cover_letter")
        assert len(val) > 50
        assert "Vatsal" in val or "software engineer" in val.lower()

    def test_referral(self):
        val = _get_resume_value("referral")
        assert val == "LinkedIn"

    def test_unknown_key_returns_empty(self):
        val = _get_resume_value("nonexistent_key_xyz")
        assert val == ""


class TestFieldMappings:
    def test_all_mappings_are_lowercase(self):
        for key in FIELD_MAPPINGS:
            assert key == key.lower(), f"Field mapping key '{key}' should be lowercase"

    def test_all_mappings_have_valid_resume_keys(self):
        valid_keys = {
            "first_name", "last_name", "full_name", "email", "phone",
            "linkedin", "github", "website", "location", "city", "country",
            "school", "degree", "work_auth", "sponsorship", "cover_letter", "referral",
        }
        for key, resume_key in FIELD_MAPPINGS.items():
            assert resume_key in valid_keys, f"Resume key '{resume_key}' not in valid set"

    def test_email_mapped(self):
        assert "email" in FIELD_MAPPINGS
        assert FIELD_MAPPINGS["email"] == "email"

    def test_first_name_mapped(self):
        assert "first name" in FIELD_MAPPINGS
        assert FIELD_MAPPINGS["first name"] == "first_name"


class TestAutoApplyGreenhouseStructure:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """Should always return a dict with expected keys."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=True)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse("https://boards.greenhouse.io/test/jobs/123")
            assert isinstance(result, dict)
            assert "success" in result
            assert "fields_filled" in result
            assert "resume_uploaded" in result
            assert "submitted" in result
            assert "url" in result
            assert "screenshot" in result

    @pytest.mark.asyncio
    async def test_dry_run_does_not_submit(self):
        """When dry_run=True, should never click submit."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=True)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse(
                "https://boards.greenhouse.io/test/jobs/123",
                dry_run=True,
            )
            assert result["submitted"] is False
            assert result["dry_run"] is True

    @pytest.mark.asyncio
    async def test_no_pdf_path_skips_upload(self):
        """When pdf_path is None, resume_uploaded should be False."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=True)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse(
                "https://boards.greenhouse.io/test/jobs/123",
                pdf_path=None,
            )
            assert result["resume_uploaded"] is False

    @pytest.mark.asyncio
    async def test_invalid_pdf_path_skips_upload(self):
        """When pdf_path points to non-existent file, resume_uploaded should be False."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=True)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse(
                "https://boards.greenhouse.io/test/jobs/123",
                pdf_path="/tmp/nonexistent_file_12345.pdf",
            )
            assert result["resume_uploaded"] is False

    @pytest.mark.asyncio
    async def test_no_form_detected_returns_error(self):
        """When no application form is found, return error."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=False)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse("https://example.com/not-a-form")
            assert result["success"] is False
            assert "error" in result
            assert "No application form" in result["error"]

    @pytest.mark.asyncio
    async def test_screenshot_saved(self):
        """Should save a screenshot and return the path."""
        with patch("outreach.greenhouse_apply.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_page = _make_mock_page(form_detected=True)
            mock_browser.new_page = AsyncMock(return_value=mock_page)
            mock_browser.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_pw.return_value = mock_context

            result = await auto_apply_greenhouse("https://boards.greenhouse.io/test/jobs/123")
            assert result["screenshot"] is not None
            assert result["screenshot"].endswith(".png")
