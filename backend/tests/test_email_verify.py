"""Tests for outreach/email_verify.py — MX record and domain validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from outreach.email_verify import (
    has_mx_record,
    is_valid_email_domain,
    verify_email_before_send,
    DISPOSABLE_DOMAINS,
    CATCH_ALL_DOMAINS,
)


class TestHasMxRecord:
    def test_gmail_has_mx(self):
        """gmail.com is a real domain with MX records."""
        assert has_mx_record("gmail.com") is True

    def test_googlemail_has_mx(self):
        assert has_mx_record("googlemail.com") is True

    def test_outlook_has_mx(self):
        assert has_mx_record("outlook.com") is True

    def test_nonexistent_domain_has_no_mx(self):
        """A domain that does not exist should have no MX records."""
        assert has_mx_record("this-domain-definitely-does-not-exist-12345.xyz") is False

    def test_empty_domain_returns_false(self):
        assert has_mx_record("") is False

    def test_invalid_domain_no_dot_returns_false(self):
        assert has_mx_record("nodot") is False

    def test_subdomain_mx_check(self):
        """mail.google.com should resolve (CNAME/A record, but MX check should fail)."""
        # mail.google.com has no MX records directly
        result = has_mx_record("mail.google.com")
        # This may or may not have MX, just ensure it doesn't crash
        assert isinstance(result, bool)


class TestIsValidEmailDomain:
    def test_valid_gmail_email(self):
        result = is_valid_email_domain("user@gmail.com")
        assert result["valid"] is True
        assert result["has_mx"] is True
        assert result["is_catch_all"] is True

    def test_valid_outlook_email(self):
        result = is_valid_email_domain("user@outlook.com")
        assert result["valid"] is True
        assert result["is_catch_all"] is True

    def test_disposable_email_blocked(self):
        for domain in list(DISPOSABLE_DOMAINS)[:3]:
            result = is_valid_email_domain(f"user@{domain}")
            assert result["valid"] is False, f"{domain} should be blocked"
            assert result["is_disposable"] is True

    def test_nonexistent_domain_blocked(self):
        result = is_valid_email_domain("user@this-domain-does-not-exist-12345.xyz")
        assert result["valid"] is False
        assert result["has_mx"] is False
        assert "no MX records" in result["reason"]

    def test_invalid_format_no_at_sign(self):
        result = is_valid_email_domain("notanemail")
        assert result["valid"] is False
        assert "no domain" in result["reason"]

    def test_invalid_format_empty_string(self):
        result = is_valid_email_domain("")
        assert result["valid"] is False

    def test_company_domain_real(self):
        """stripe.com should have MX records and not be disposable/catch-all."""
        result = is_valid_email_domain("careers@stripe.com")
        assert result["valid"] is True
        assert result["has_mx"] is True
        assert result["is_disposable"] is False
        assert result["is_catch_all"] is False

    def test_returns_dict_with_all_keys(self):
        result = is_valid_email_domain("test@gmail.com")
        assert "valid" in result
        assert "has_mx" in result
        assert "is_disposable" in result
        assert "is_catch_all" in result
        assert "reason" in result


class TestVerifyEmailBeforeSend:
    def test_gmail_allowed(self):
        assert verify_email_before_send("user@gmail.com") is True

    def test_disposable_blocked(self):
        for domain in list(DISPOSABLE_DOMAINS)[:3]:
            assert verify_email_before_send(f"user@{domain}") is False

    def test_nonexistent_blocked(self):
        assert verify_email_before_send("user@fake-domain-12345.xyz") is False

    def test_empty_email_blocked(self):
        assert verify_email_before_send("") is False

    def test_no_at_sign_blocked(self):
        assert verify_email_before_send("notanemail") is False
