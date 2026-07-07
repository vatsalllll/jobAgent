"""Tests for Hacker News and Indeed job scrapers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from discover.hackernews import (
    _extract_company_name,
    _extract_url,
    _extract_role_title,
    _is_junior_role,
    _is_senior_role,
    _find_latest_hiring_thread,
    _parse_comment,
)
from discover.indeed_rss import (
    _extract_company_from_title,
    _extract_role_from_title,
    _is_junior_role as _is_junior_role_indeed,
    _is_senior_role as _is_senior_role_indeed,
    _parse_date,
)


class TestHnExtractCompanyName:
    def test_simple_company(self):
        text = "Stripe - Software Engineer\nWe are building..."
        assert _extract_company_name(text) == "Stripe"

    def test_bullet_prefix(self):
        text = "* Google\nSoftware Engineer, Backend..."
        assert _extract_company_name(text) == "Google"

    def test_dash_prefix(self):
        text = "- Airbnb\nFull Stack Engineer..."
        assert _extract_company_name(text) == "Airbnb"

    def test_empty_text(self):
        assert _extract_company_name("") == ""


class TestHnExtractUrl:
    def test_simple_url(self):
        text = "Apply at https://company.com/careers/engineering"
        assert _extract_url(text) == "https://company.com/careers/engineering"

    def test_url_with_punctuation(self):
        text = "See https://stripe.com/jobs (remote)"
        assert _extract_url(text) == "https://stripe.com/jobs"

    def test_no_url(self):
        assert _extract_url("No link here") == ""

    def test_multiple_urls(self):
        text = "Check https://a.com and https://b.com"
        assert _extract_url(text) == "https://a.com"


class TestHnExtractRoleTitle:
    def test_dash_separator(self):
        text = "OpenAI - ML Engineer\nWe are..."
        assert _extract_role_title(text) == "ML Engineer"

    def test_pipe_separator(self):
        text = "Notion | Backend Engineer\nBuild..."
        assert _extract_role_title(text) == "Backend Engineer"

    def test_role_keyword_in_text(self):
        text = "We are hiring a software engineer to build..."
        assert "software engineer" in _extract_role_title(text).lower()

    def test_empty_text(self):
        assert _extract_role_title("") == ""


class TestHnRoleFilters:
    def test_junior_intern(self):
        assert _is_junior_role("Software Engineer Intern") is True

    def test_junior_entry_level(self):
        assert _is_junior_role("Entry Level Backend Engineer") is True

    def test_not_junior(self):
        assert _is_junior_role("Senior Software Engineer") is False

    def test_senior_role(self):
        assert _is_senior_role("Senior Backend Engineer") is True

    def test_staff_role(self):
        assert _is_senior_role("Staff Engineer") is True

    def test_not_senior(self):
        assert _is_senior_role("Software Engineer") is False


class TestHnParseComment:
    def test_valid_job_post(self):
        comment = {
            "id": "12345",
            "text": "<p>Stripe - Software Engineer</p><p>We're building payment infrastructure. Remote.</p><p>https://stripe.com/jobs</p>",
        }
        job = _parse_comment(comment)
        assert job is not None
        assert job.company == "Stripe"
        assert "software engineer" in job.title.lower()
        assert job.source == "hackernews"
        assert job.is_remote is True

    def test_senior_role_skipped(self):
        comment = {
            "id": "12346",
            "text": "<p>Google - Senior Staff Engineer</p><p>Lead teams.</p>",
        }
        job = _parse_comment(comment)
        assert job is None

    def test_non_tech_role_skipped(self):
        comment = {
            "id": "12347",
            "text": "<p>Acme Corp - Sales Representative</p><p>Sell things.</p>",
        }
        job = _parse_comment(comment)
        assert job is None

    def test_too_short_text_skipped(self):
        comment = {
            "id": "12348",
            "text": "<p>Hi</p>",
        }
        job = _parse_comment(comment)
        assert job is None


class TestHnFindLatestHiringThread:
    @pytest.mark.asyncio
    async def test_returns_int_or_none(self):
        """Should return a thread ID (int) or None, never crash."""
        result = await _find_latest_hiring_thread()
        assert result is None or isinstance(result, (int, str)), f"Unexpected type: {type(result)}"


class TestIndeedExtractCompany:
    def test_dash_separator(self):
        assert _extract_company_from_title("Software Engineer - Google") == "Google"

    def test_at_separator(self):
        assert _extract_company_from_title("Backend Engineer at Stripe") == "Stripe"

    def test_pipe_separator(self):
        assert _extract_company_from_title("Full Stack | Airbnb") == "Airbnb"

    def test_no_separator(self):
        assert _extract_company_from_title("Software Engineer") == ""


class TestIndeedExtractRole:
    def test_dash_separator(self):
        assert _extract_role_from_title("Software Engineer - Google") == "Software Engineer"

    def test_at_separator(self):
        assert _extract_role_from_title("Backend Engineer at Stripe") == "Backend Engineer"

    def test_no_separator(self):
        assert _extract_role_from_title("Software Engineer") == "Software Engineer"


class TestIndeedRoleFilters:
    def test_junior_intern(self):
        assert _is_junior_role_indeed("Software Engineer Intern") is True

    def test_fresher(self):
        assert _is_junior_role_indeed("Fresher Java Developer") is True

    def test_not_junior(self):
        assert _is_junior_role_indeed("Senior Software Engineer") is False

    def test_senior(self):
        assert _is_senior_role_indeed("Senior Architect") is True


class TestIndeedParseDate:
    def test_rss_date_format(self):
        date_str = "Mon, 06 Jul 2026 14:30:00 GMT"
        result = _parse_date(date_str)
        assert result is not None
        assert result.year == 2026

    def test_iso_format(self):
        date_str = "2026-07-06T14:30:00Z"
        result = _parse_date(date_str)
        assert result is not None
        assert result.year == 2026

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_none(self):
        assert _parse_date(None) is None
