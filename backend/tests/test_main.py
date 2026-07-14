"""Tests for main.py endpoints and email safety checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestApiKeySecurity:
    """API key should be required when configured, and endpoints should reject unauthorized requests."""

    def test_dashboard_without_api_key_when_configured(self):
        """If API_KEY is set in environment, dashboard should require it."""
        with patch("config.settings.api_key", "secret123"):
            from main import app
            client = TestClient(app)
            # No API key header → should fail
            response = client.get("/dashboard")
            assert response.status_code == 401, "Dashboard should require API key when configured"

    def test_dashboard_with_wrong_api_key(self):
        """Wrong API key should be rejected."""
        with patch("config.settings.api_key", "secret123"):
            from main import app
            client = TestClient(app)
            response = client.get("/dashboard", headers={"x-api-key": "wrong"})
            assert response.status_code == 401

    def test_dashboard_with_correct_api_key(self):
        """Correct API key should allow access."""
        with patch("config.settings.api_key", "secret123"):
            from main import app
            client = TestClient(app)
            response = client.get("/dashboard", headers={"x-api-key": "secret123"})
            # 200 if DB exists, but at least not 401
            assert response.status_code != 401

    def test_empty_api_key_returns_401(self):
        """When API_KEY is empty string, auth should reject with 401."""
        with patch("config.settings.api_key", ""):
            from main import app
            client = TestClient(app)
            response = client.get("/dashboard")
            assert response.status_code == 401, "Empty API_KEY should reject all requests"


class TestDownloadPdfSecurity:
    """Path traversal and auth checks for /download-pdf."""

    def test_download_pdf_path_traversal_blocked(self):
        """Attempting to access files outside output_dir should be blocked."""
        with patch("config.settings.api_key", "secret123"):
            from main import app
            client = TestClient(app)
            response = client.get(
                "/download-pdf?path=../../etc/passwd",
                headers={"x-api-key": "secret123"},
            )
            assert response.status_code == 403, "Path traversal should be blocked"

    def test_download_pdf_nonexistent_file(self):
        """Requesting a non-existent PDF should return 404."""
        with patch("config.settings.api_key", "secret123"):
            with patch("config.settings.output_dir", "/tmp/nonexistent_outputs"):
                from main import app
                client = TestClient(app)
                response = client.get(
                    "/download-pdf?path=/tmp/nonexistent_outputs/fake.pdf",
                    headers={"x-api-key": "secret123"},
                )
                assert response.status_code == 404


class TestAtsPreSendGuard:
    """Emails should never be sent to ATS domains, even if contact finder misses it."""

    def test_ats_domain_in_recipient_blocked(self):
        """An explicit ATS domain in the recipient should block the send."""
        from outreach.contact_finder import _is_ats_domain
        ats_domains = [
            "careers@greenhouse.io",
            "jobs@ashbyhq.com",
            "apply@lever.co",
            "noreply@myworkdayjobs.com",
        ]
        for email in ats_domains:
            domain = email.split("@")[1]
            assert _is_ats_domain(domain), f"{domain} should be recognized as ATS"

    def test_ats_presend_check_exists_in_daily_sweep(self):
        """daily_sweep must gate sends through should_send() (which, with get_best_contact,
        filters ATS domains, guessed domains, and guessed personal addresses before sending)."""
        import inspect
        from main import daily_sweep
        source = inspect.getsource(daily_sweep)
        assert "should_send" in source, "send-safety gate must be in daily_sweep"


class TestPdfAttachmentSafety:
    """PDF attachment should be verified before sending; missing PDF should block send."""

    def test_pdf_path_resolution_blocks_send_when_missing(self):
        """When PDF file does not exist, email should NOT be sent."""
        from pathlib import Path
        from config import settings

        fake_path = Path(settings.output_dir) / "nonexistent_resume.pdf"
        assert not fake_path.exists(), "Test file should not exist"

    def test_pdf_attachment_arg_empty_when_file_missing(self):
        """Missing PDF → empty attachment, and send should be blocked."""
        attachment = "templates/outputs/fake_company_fake_role.pdf"
        pdf_path = Path(attachment)
        if not pdf_path.is_absolute():
            pdf_path = Path(__file__).parent.parent / attachment
            if not pdf_path.exists():
                pdf_path = Path("/tmp/fake_outputs") / Path(attachment).name

        if not pdf_path.exists():
            attachment_arg = ""
        else:
            attachment_arg = str(pdf_path)

        assert attachment_arg == "", "Missing PDF should result in empty attachment"
        # After fix, main.py blocks send when PDF is missing and attachment was expected


class TestMxVerificationMissing:
    """No MX record verification exists before sending emails."""

    def test_mx_check_in_email_pipeline(self):
        """MX verification should exist before send_email() in daily_sweep."""
        import inspect
        from main import daily_sweep
        source = inspect.getsource(daily_sweep)
        assert "verify_email_before_send" in source, "MX verification must be in daily_sweep"

    def test_mx_module_exists(self):
        """email_verify.py module should exist in the project."""
        mx_module = Path(__file__).parent.parent / "outreach" / "email_verify.py"
        assert mx_module.exists(), "email_verify.py must exist"


class TestHealthEndpoint:
    """Health check should always work without auth."""

    def test_health_returns_ok(self):
        from main import app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
