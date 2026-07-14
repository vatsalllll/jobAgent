import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from outreach.contact_finder import (
    _is_ats_domain,
    _score_contact,
    get_best_contact,
    find_company_domain,
    ATS_DOMAINS,
    CONTACT_PATTERNS,
    FOUNDER_TITLES,
    RECRUITER_TITLES,
)


class TestIsAtsDomain:
    def test_ashbyhq(self):
        assert _is_ats_domain("ashbyhq.com") is True

    def test_ashbyhq_subdomain(self):
        assert _is_ats_domain("jobs.ashbyhq.com") is True

    def test_greenhouse(self):
        assert _is_ats_domain("greenhouse.io") is True

    def test_greenhouse_subdomain(self):
        assert _is_ats_domain("boards.greenhouse.io") is True

    def test_lever(self):
        assert _is_ats_domain("lever.co") is True

    def test_lever_subdomain(self):
        assert _is_ats_domain("jobs.lever.co") is True

    def test_workable(self):
        assert _is_ats_domain("workable.com") is True

    def test_workable_subdomain(self):
        assert _is_ats_domain("apply.workable.com") is True

    def test_myworkdayjobs(self):
        assert _is_ats_domain("myworkdayjobs.com") is True

    def test_smartrecruiters(self):
        assert _is_ats_domain("smartrecruiters.com") is True

    def test_non_ats_company(self):
        assert _is_ats_domain("openai.com") is False

    def test_non_ats_stripe(self):
        assert _is_ats_domain("stripe.com") is False

    def test_non_ats_modal(self):
        assert _is_ats_domain("modal.com") is False

    def test_empty_string(self):
        assert _is_ats_domain("") is False

    def test_none(self):
        assert _is_ats_domain(None) is False

    def test_case_insensitive(self):
        assert _is_ats_domain("ASHBYHQ.COM") is True

    def test_no_leading_space_in_ats_domains(self):
        for domain in ATS_DOMAINS:
            assert domain == domain.strip(), f"ATS domain '{domain}' has leading/trailing whitespace"


class TestScoreContact:
    def test_founder_scores_higher_than_recruiter(self):
        founder = {"email": "ceo@company.com", "position": "CEO", "type": "personal", "confidence": "high", "source": "hunter"}
        recruiter = {"email": "hiring@company.com", "position": "Recruiter", "type": "personal", "confidence": "high", "source": "hunter"}
        assert _score_contact(founder) > _score_contact(recruiter)

    def test_hunter_source_boosts_score(self):
        hunter = {"email": "john@company.com", "position": "Engineer", "type": "personal", "confidence": "high", "source": "hunter"}
        pattern = {"email": "john@company.com", "position": "Engineer", "type": "personal", "confidence": "high", "source": "pattern"}
        assert _score_contact(hunter) > _score_contact(pattern)

    def test_high_confidence_boosts_score(self):
        high = {"email": "john@company.com", "position": "Engineer", "type": "personal", "confidence": "high", "source": "hunter"}
        low = {"email": "john@company.com", "position": "Engineer", "type": "personal", "confidence": "low", "source": "hunter"}
        assert _score_contact(high) > _score_contact(low)

    def test_verified_personal_beats_generic_pattern(self):
        # A verified real personal contact must outrank a generic (guessed) role-address pattern.
        verified_personal = {"email": "john@company.com", "position": "", "type": "personal", "confidence": "medium", "source": "github_public"}
        generic_pattern = {"email": "careers@company.com", "position": "", "type": "careers", "confidence": "low", "source": "pattern"}
        assert _score_contact(verified_personal) > _score_contact(generic_pattern)

    def test_guessed_founder_does_not_beat_verified_email(self):
        # Regression guard for the old inversion: a guessed YC-founder address must NOT
        # outrank a real, verified personal email.
        guessed_founder = {"email": "jane.doe@company.com", "position": "Founder", "type": "personal", "confidence": "medium", "source": "yc_api"}
        verified = {"email": "jane@company.com", "position": "", "type": "personal", "confidence": "medium", "source": "github_public"}
        assert _score_contact(verified) > _score_contact(guessed_founder)

    def test_founder_email_pattern_boosts_score(self):
        founder_email = {"email": "founder@company.com", "position": "", "type": "", "confidence": "low", "source": "pattern"}
        hello_email = {"email": "hello@company.com", "position": "", "type": "", "confidence": "low", "source": "pattern"}
        assert _score_contact(founder_email) > _score_contact(hello_email)

    def test_empty_contact_scores_zero(self):
        contact = {"email": "", "position": "", "type": "", "confidence": "", "source": ""}
        assert _score_contact(contact) == 0


class TestGetBestContact:
    def test_empty_list_returns_empty(self):
        result = get_best_contact([])
        assert result["email"] == ""
        assert result["source"] == "none"

    def test_returns_highest_scored_contact(self):
        contacts = [
            {"email": "careers@company.com", "position": "", "type": "careers", "confidence": "low", "source": "pattern", "name": ""},
            {"email": "ceo@company.com", "position": "CEO", "type": "personal", "confidence": "high", "source": "hunter", "name": "CEO"},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == "ceo@company.com"

    def test_filters_ats_domain_email(self):
        contacts = [
            {"email": "careers@jobs.ashbyhq.com", "position": "", "type": "careers", "confidence": "low", "source": "pattern", "name": ""},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == ""

    def test_filters_greenhouse_ats_domain(self):
        contacts = [
            {"email": "jobs@boards.greenhouse.io", "position": "", "type": "jobs", "confidence": "low", "source": "pattern", "name": ""},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == ""

    def test_filters_lever_ats_domain(self):
        contacts = [
            {"email": "apply@jobs.lever.co", "position": "", "type": "", "confidence": "low", "source": "pattern", "name": ""},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == ""

    def test_picks_non_ats_over_ats(self):
        contacts = [
            {"email": "careers@jobs.ashbyhq.com", "position": "CEO", "type": "personal", "confidence": "high", "source": "hunter", "name": "CEO"},
            {"email": "ceo@modal.com", "position": "CEO", "type": "personal", "confidence": "high", "source": "hunter", "name": "CEO"},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == "ceo@modal.com"

    def test_contact_without_at_sign_returns_empty(self):
        contacts = [
            {"email": "not-an-email", "position": "CEO", "type": "personal", "confidence": "high", "source": "hunter", "name": "CEO"},
        ]
        result = get_best_contact(contacts)
        assert result["email"] == ""


class TestFindCompanyDomain:
    @pytest.mark.asyncio
    async def test_ashby_url_returns_company_domain(self):
        domain = await find_company_domain("Modal", "https://jobs.ashbyhq.com/modal")
        assert domain == "modal.com"
        assert _is_ats_domain(domain) is False

    @pytest.mark.asyncio
    async def test_greenhouse_url_returns_company_domain(self):
        domain = await find_company_domain("OpenAI", "https://boards.greenhouse.io/openai")
        assert domain == "openai.com"
        assert _is_ats_domain(domain) is False

    @pytest.mark.asyncio
    async def test_lever_url_returns_company_domain(self):
        domain = await find_company_domain("Spotify", "https://jobs.lever.co/spotify")
        assert domain == "spotify.com"
        assert _is_ats_domain(domain) is False

    @pytest.mark.asyncio
    async def test_direct_company_url(self):
        domain = await find_company_domain("Stripe", "https://stripe.com/careers")
        assert domain == "stripe.com"

    @pytest.mark.asyncio
    async def test_no_url_guesses_domain(self):
        domain = await find_company_domain("Linear", "")
        assert domain == "linear.com"

    @pytest.mark.asyncio
    async def test_empty_company_name_returns_empty(self):
        # An empty company name must NOT resolve to a real company's domain (old bug: it
        # matched the first COMMON_DOMAINS entry, "stripe.com").
        domain = await find_company_domain("", "")
        assert domain == ""

    @pytest.mark.asyncio
    async def test_company_name_with_parens_stripped(self):
        domain = await find_company_domain("Acme (YC W24)", "")
        assert domain == "acmeycw24.com" or "acme" in domain

    @pytest.mark.asyncio
    async def test_known_domain_lookup(self):
        domain = await find_company_domain("Stripe", "")
        assert domain == "stripe.com"

    @pytest.mark.asyncio
    async def test_ats_url_does_not_return_ats_domain(self):
        domain = await find_company_domain("SomeCompany", "https://jobs.ashbyhq.com/somecompany")
        assert _is_ats_domain(domain) is False


class TestContactPatterns:
    def test_patterns_contain_domain_placeholder(self):
        for pattern in CONTACT_PATTERNS:
            assert "{domain}" in pattern, f"Pattern '{pattern}' missing {{domain}} placeholder"

    def test_patterns_generate_valid_emails(self):
        for pattern in CONTACT_PATTERNS:
            email = pattern.replace("{domain}", "company.com")
            assert "@" in email
            assert email.endswith("@company.com")


class TestTitleLists:
    def test_founder_titles_are_lowercase(self):
        for title in FOUNDER_TITLES:
            assert title == title.lower(), f"Founder title '{title}' should be lowercase"

    def test_recruiter_titles_are_lowercase(self):
        for title in RECRUITER_TITLES:
            assert title == title.lower(), f"Recruiter title '{title}' should be lowercase"
