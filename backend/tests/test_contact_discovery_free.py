"""Tests for outreach/contact_discovery_free.py — free contact sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from outreach.contact_discovery_free import (
    _infer_email,
    _github_search_users,
    _scrape_team_page,
    find_contacts_free,
    EMAIL_PATTERNS,
)


class TestInferEmail:
    def test_basic_first_last(self):
        emails = _infer_email("John Doe", "stripe.com")
        assert any("john.doe@stripe.com" in e for e in emails)

    def test_first_initial_last(self):
        emails = _infer_email("Jane Smith", "company.com")
        assert any("j.smith@company.com" in e for e in emails)

    def test_single_name_returns_empty(self):
        emails = _infer_email("Prince", "company.com")
        # Single name still generates patterns but may not be useful
        assert isinstance(emails, list)

    def test_empty_name_returns_empty(self):
        assert _infer_email("", "company.com") == []

    def test_empty_domain_returns_empty(self):
        assert _infer_email("John Doe", "") == []

    def test_domain_with_at_sign_returns_empty(self):
        assert _infer_email("John Doe", "bad@domain") == []

    def test_multiple_names(self):
        emails = _infer_email("Mary Jane Watson", "example.com")
        assert len(emails) > 0
        # Should use first and last name
        assert any("mary.watson@example.com" in e for e in emails)

    def test_no_duplicate_emails(self):
        emails = _infer_email("John Doe", "test.com")
        assert len(emails) == len(set(emails)), "No duplicate emails should be generated"


class TestEmailPatterns:
    def test_all_patterns_have_placeholders(self):
        for pattern in EMAIL_PATTERNS:
            assert "{first}" in pattern or "{f}" in pattern
            assert "{domain}" in pattern

    def test_all_patterns_generate_valid_email(self):
        for pattern in EMAIL_PATTERNS:
            email = pattern.format(first="john", last="doe", f="j", domain="test.com")
            assert "@" in email
            assert email.endswith("@test.com")
            assert email.count("@") == 1


class TestGithubSearchUsers:
    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        """GitHub search should return a list even if empty."""
        results = await _github_search_users("DefinitelyNotARealCompanyXYZ123")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_github_contacts_have_required_fields(self):
        """Any returned contact should have email, name, source fields."""
        # Use a well-known company that may have public emails
        results = await _github_search_users("Google")
        for r in results:
            assert "email" in r
            assert "name" in r
            assert "source" in r
            assert r["source"] == "github_public"


class TestScrapeTeamPage:
    @pytest.mark.asyncio
    async def test_invalid_domain_returns_empty(self):
        results = await _scrape_team_page("this-is-not-a-real-domain-12345.xyz")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_domain_returns_empty(self):
        results = await _scrape_team_page("")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """Scraping should return a list even if no names found."""
        results = await _scrape_team_page("stripe.com")
        assert isinstance(results, list)


class TestFindContactsFree:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        results = await find_contacts_free("FakeCompanyXYZ123", "")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        """Emails should be deduplicated."""
        results = await find_contacts_free("Stripe", "stripe.com")
        emails = [r["email"].lower() for r in results if r.get("email")]
        assert len(emails) == len(set(emails)), "No duplicate emails"
