"""End-to-end integration tests for the Job Agent API.

These tests start the FastAPI application and exercise real endpoints
with mocked external dependencies where appropriate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client():
    """Create a test client with a mocked API key."""
    with patch("config.settings.api_key", "test-api-key-123"):
        from main import app
        yield TestClient(app)


class TestDiscoverJobsIntegration:
    def test_discover_jobs_with_mocked_source(self, client):
        """Test /discover-jobs endpoint returns structured data."""
        with patch("main.scrape_github", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.return_value = []
            response = client.post("/discover-jobs?sources=github&max_age_days=7")
            assert response.status_code == 200
            data = response.json()
            assert "jobs" in data
            assert "total_found" in data
            assert "total_filtered" in data
            assert "errors" in data

    def test_discover_jobs_requires_no_auth(self, client):
        """/discover-jobs should be publicly accessible."""
        with patch("main.scrape_github", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.return_value = []
            response = client.post("/discover-jobs?sources=github")
            assert response.status_code == 200


class TestTailorResumeIntegration:
    def test_tailor_resume_returns_tailored_data(self, client):
        """Test /tailor-resume returns structured resume data."""
        with patch("main.tailor_resume", new_callable=AsyncMock) as mock_tailor:
            with patch("main.score_match", new_callable=AsyncMock) as mock_score:
                with patch("main.verify_fidelity", new_callable=AsyncMock) as mock_verify:
                    with patch("main.render_pdf_inline", new_callable=AsyncMock) as mock_pdf:
                        mock_tailor.return_value = {
                            "basics": {"name": "Test User", "label": "Software Engineer"},
                            "work": [],
                            "education": [],
                        }
                        mock_score.return_value = {"match_score": 85, "keywords_matched": ["python"]}
                        mock_verify.return_value = {"is_faithful": True, "issues": []}
                        mock_pdf.return_value = "/tmp/test.pdf"

                        response = client.post(
                            "/tailor-resume",
                            json={
                                "job_id": "test-1",
                                "job_title": "Software Engineer",
                                "company": "TestCo",
                                "job_description": "Python, FastAPI, React",
                            },
                        )
                        assert response.status_code == 200
                        data = response.json()
                        assert data["job_id"] == "test-1"
                        assert data["match_score"] == 85
                        assert "tailored_resume" in data


class TestGenerateEmailIntegration:
    def test_generate_email_returns_email_data(self, client):
        """Test /generate-email returns structured email data."""
        with patch("main.generate_outreach_email", new_callable=AsyncMock) as mock_email:
            mock_email.return_value = {
                "subject": "Software Engineer — Test User",
                "body": "Hello, I'm interested in...",
            }

            response = client.post(
                "/generate-email",
                json={
                    "job_title": "Software Engineer",
                    "company": "TestCo",
                    "job_description": "Python role",
                    "tailored_resume": {"basics": {"name": "Test User"}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "subject" in data
            assert "body" in data


class TestDailySweepIntegration:
    def test_daily_sweep_runs_without_errors(self, client):
        """Test /daily-sweep runs the full pipeline with mocked dependencies."""
        with patch("main.discover_jobs", new_callable=AsyncMock) as mock_discover:
            with patch("main.tailor_resume_endpoint", new_callable=AsyncMock) as mock_tailor:
                with patch("main.generate_outreach_email", new_callable=AsyncMock) as mock_email:
                        with patch("main.discover_company_info", new_callable=AsyncMock) as mock_info:
                            with patch("outreach.google_auth.send_email") as mock_send:
                                with patch("main.log_sweep"):
                                    with patch("main.log_application"):
                                        from discover.models import JobListing
                                        from datetime import datetime, timezone

                                        mock_discover.return_value = type("obj", (object,), {
                                            "jobs": [
                                                JobListing(
                                                    id="test-1",
                                                    title="Software Engineer",
                                                    company="TestCo",
                                                    location="Remote",
                                                    url="https://testco.com/jobs",
                                                    source="github",
                                                    description="Python role",
                                                    posted_date=datetime.now(timezone.utc),
                                                ),
                                            ],
                                            "total_filtered": 1,
                                        })()
                                        mock_tailor.return_value = type("obj", (object,), {
                                            "match_score": 75,
                                            "pdf_path": "/tmp/test.pdf",
                                            "tailored_resume": {"basics": {"name": "Test"}},
                                        })()
                                        mock_email.return_value = {"subject": "Test", "body": "Hello"}
                                        mock_info.return_value = {
                                            "contacts": [
                                                {"email": "hiring@testco.com", "name": "HR", "position": "Recruiter", "source": "pattern", "confidence": "low", "type": "hiring"},
                                            ],
                                            "linkedin_contacts": [],
                                            "careers_page": "",
                                        }
                                        mock_send.return_value = {"id": "msg123"}

                                        response = client.post("/daily-sweep?sources=github&max_jobs=1&tailor=true&generate_emails=true")
                                        assert response.status_code == 200
                                        data = response.json()
                                        assert "sweep_id" in data
                                        assert "jobs_found" in data
                                        assert "emails_generated" in data

    def test_daily_sweep_skips_ats_domain(self, client):
        """Test that daily_sweep skips sending to ATS domains even if contact finder misses it."""
        with patch("main.discover_jobs", new_callable=AsyncMock) as mock_discover:
            with patch("main.tailor_resume_endpoint", new_callable=AsyncMock) as mock_tailor:
                with patch("main.generate_outreach_email", new_callable=AsyncMock) as mock_email:
                        with patch("main.discover_company_info", new_callable=AsyncMock) as mock_info:
                            with patch("outreach.google_auth.send_email") as mock_send:
                                with patch("main.log_sweep"):
                                    with patch("main.log_application"):
                                        from discover.models import JobListing
                                        from datetime import datetime, timezone

                                        mock_discover.return_value = type("obj", (object,), {
                                            "jobs": [
                                                JobListing(
                                                    id="test-2",
                                                    title="Engineer",
                                                    company="BadCo",
                                                    location="Remote",
                                                    url="https://badco.com",
                                                    source="github",
                                                    description="Role",
                                                    posted_date=datetime.now(timezone.utc),
                                                ),
                                            ],
                                            "total_filtered": 1,
                                        })()
                                        mock_tailor.return_value = type("obj", (object,), {
                                            "match_score": 75,
                                            "pdf_path": "/tmp/test.pdf",
                                            "tailored_resume": {"basics": {"name": "Test"}},
                                        })()
                                        mock_email.return_value = {"subject": "Test", "body": "Hello"}
                                        # Force an ATS domain email through contact finder
                                        mock_info.return_value = {
                                            "contacts": [
                                                {"email": "careers@greenhouse.io", "name": "ATS", "position": "", "source": "pattern", "confidence": "low", "type": "careers"},
                                            ],
                                            "linkedin_contacts": [],
                                            "careers_page": "",
                                        }

                                        response = client.post("/daily-sweep?sources=github&max_jobs=1&tailor=true&generate_emails=true")
                                        assert response.status_code == 200
                                        # send_email should NOT have been called because ATS domain is blocked
                                        mock_send.assert_not_called()

    def test_daily_sweep_skips_mx_fail(self, client):
        """Test that daily_sweep skips sending when MX verification fails."""
        with patch("main.discover_jobs", new_callable=AsyncMock) as mock_discover:
            with patch("main.tailor_resume_endpoint", new_callable=AsyncMock) as mock_tailor:
                with patch("main.generate_outreach_email", new_callable=AsyncMock) as mock_email:
                        with patch("main.discover_company_info", new_callable=AsyncMock) as mock_info:
                            with patch("outreach.google_auth.send_email") as mock_send:
                                with patch("main.log_sweep"):
                                    with patch("main.log_application"):
                                        from discover.models import JobListing
                                        from datetime import datetime, timezone

                                        mock_discover.return_value = type("obj", (object,), {
                                            "jobs": [
                                                JobListing(
                                                    id="test-3",
                                                    title="Engineer",
                                                    company="FakeCo",
                                                    location="Remote",
                                                    url="https://fakeco.com",
                                                    source="github",
                                                    description="Role",
                                                    posted_date=datetime.now(timezone.utc),
                                                ),
                                            ],
                                            "total_filtered": 1,
                                        })()
                                        mock_tailor.return_value = type("obj", (object,), {
                                            "match_score": 75,
                                            "pdf_path": "/tmp/test.pdf",
                                            "tailored_resume": {"basics": {"name": "Test"}},
                                        })()
                                        mock_email.return_value = {"subject": "Test", "body": "Hello"}
                                        mock_info.return_value = {
                                            "contacts": [
                                                {"email": "hr@this-domain-does-not-exist-12345.xyz", "name": "HR", "position": "", "source": "pattern", "confidence": "low", "type": "hr"},
                                            ],
                                            "linkedin_contacts": [],
                                            "careers_page": "",
                                        }

                                        response = client.post("/daily-sweep?sources=github&max_jobs=1&tailor=true&generate_emails=true")
                                        assert response.status_code == 200
                                        mock_send.assert_not_called()


class TestDashboardIntegration:
    def test_dashboard_with_api_key(self, client):
        """Test /dashboard with correct API key."""
        response = client.get("/dashboard", headers={"x-api-key": "test-api-key-123"})
        assert response.status_code != 401

    def test_dashboard_without_api_key(self, client):
        """Test /dashboard without API key returns 401."""
        response = client.get("/dashboard")
        assert response.status_code == 401


class TestDownloadPdfIntegration:
    def test_download_pdf_with_api_key(self, client):
        """Test /download-pdf requires API key."""
        response = client.get("/download-pdf?path=fake.pdf", headers={"x-api-key": "test-api-key-123"})
        assert response.status_code in [404, 403]  # Either file not found or path blocked

    def test_download_pdf_without_api_key(self, client):
        response = client.get("/download-pdf?path=fake.pdf")
        assert response.status_code == 401
