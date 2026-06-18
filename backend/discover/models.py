"""Job data models."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class JobListing(BaseModel):
    """A discovered job listing from any source."""

    id: str  # unique identifier (source + external_id)
    title: str
    company: str
    location: str
    url: str
    source: str  # "yc", "greenhouse", "lever", etc.
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = "INR"
    posted_date: Optional[datetime] = None
    is_remote: bool = False
    employment_type: str = ""  # "internship", "full-time", "contract"
    seniority: str = ""  # "intern", "junior", "associate"
    company_size: str = ""  # "startup", "mid", "enterprise"

    @property
    def age_days(self) -> float:
        if not self.posted_date:
            return 999
        return (datetime.now().astimezone() - self.posted_date).total_seconds() / 86400

    @property
    def salary_inr_monthly(self) -> Optional[float]:
        """Estimate monthly INR salary."""
        if not self.salary_min:
            return None
        if self.salary_currency == "INR":
            return self.salary_min / 12 if self.salary_min > 100000 else self.salary_min
        if self.salary_currency == "USD":
            # Rough conversion: 1 USD ≈ 83 INR
            return self.salary_min * 83 / 12
        return None


class DiscoveredJobs(BaseModel):
    """Result of a job discovery sweep."""

    source: str
    jobs: list[JobListing]
    total_found: int
    total_filtered: int
    errors: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    """A resume tailored for a specific job."""

    job_id: str
    content_json: dict  # JSON Resume format, tailored
    pdf_path: Optional[str] = None
    match_score: float = 0.0  # 0-100
    keywords_matched: list[str] = Field(default_factory=list)


class OutreachEmail(BaseModel):
    """Generated outreach email for a job application."""

    job_id: str
    to_email: str
    to_name: str = ""
    subject: str
    body: str
    resume_attached: bool = False
