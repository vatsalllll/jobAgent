"""Email verification utilities — MX record checks and domain validation.

All functions use free, publicly available DNS queries. No paid APIs required.
"""

import logging
from typing import Optional

import dns.resolver
import dns.exception

logger = logging.getLogger(__name__)


# Disposable / known-bad email domains to block
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "yopmail.com",
    "sharklasers.com", "throwawaymail.com", "getairmail.com", "tempinbox.com",
    "mailnesia.com", "burnermail.io",
}

# Domains that accept all email (catch-all) — harder to verify
CATCH_ALL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "ymail.com", "protonmail.com", "icloud.com", "me.com",
}


def _domain_from_email(email: str) -> str:
    """Extract domain from email address."""
    if not email or "@" not in email:
        return ""
    return email.split("@")[1].lower().strip()


def has_mx_record(domain: str) -> bool:
    """Check if a domain has MX records (accepts mail).

    Uses dnspython to query public DNS resolvers. Free, no API key needed.
    """
    if not domain or "." not in domain:
        return False
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return False
    except Exception as e:
        logger.warning(f"MX lookup failed for {domain}: {e}")
        return False


def is_valid_email_domain(email: str) -> dict:
    """Validate an email address domain comprehensively.

    Returns dict with:
        - valid: bool — can we send to this domain?
        - has_mx: bool — does domain accept mail?
        - is_disposable: bool — is it a throwaway domain?
        - is_catch_all: bool — is it a major provider (gmail, etc.)?
        - reason: str — human-readable explanation
    """
    domain = _domain_from_email(email)
    if not domain:
        return {
            "valid": False,
            "has_mx": False,
            "is_disposable": False,
            "is_catch_all": False,
            "reason": "Invalid email format (no domain)",
        }

    if domain in DISPOSABLE_DOMAINS:
        return {
            "valid": False,
            "has_mx": True,
            "is_disposable": True,
            "is_catch_all": False,
            "reason": f"Disposable email domain: {domain}",
        }

    mx_ok = has_mx_record(domain)
    is_catch_all = domain in CATCH_ALL_DOMAINS

    if not mx_ok and not is_catch_all:
        return {
            "valid": False,
            "has_mx": False,
            "is_disposable": False,
            "is_catch_all": False,
            "reason": f"Domain {domain} has no MX records — mail will bounce",
        }

    # Catch-all domains (Gmail, Outlook) always have MX but we can't verify the specific address
    return {
        "valid": True,
        "has_mx": True,
        "is_disposable": False,
        "is_catch_all": is_catch_all,
        "reason": f"Domain {domain} verified" + (" (catch-all provider)" if is_catch_all else ""),
    }


def verify_email_before_send(email: str) -> bool:
    """Quick boolean check: should we send email to this address?

    Returns True only if domain has MX records and is not disposable.
    """
    result = is_valid_email_domain(email)
    if not result["valid"]:
        logger.warning(f"Email verification failed for {email}: {result['reason']}")
    return result["valid"]
