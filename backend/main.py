"""
Job Agent — FastAPI Application
Main entry point that wires together all pipelines:
  POST /discover-jobs     → scrape YC + Greenhouse for fresh listings
  POST /tailor-resume     → Claude-tailored resume for a specific job
  POST /generate-email    → personalized outreach email
  POST /daily-sweep       → full pipeline: discover → tailor → email
  GET  /health            → health check
  GET  /dashboard         → summary of tracked applications
"""

import json
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

from config import settings
from data.base_resume import BASE_RESUME
from discover.yc_scraper import scrape_yc_jobs
from discover.greenhouse import scrape_greenhouse_all
from discover.github_jobs import scrape_github
from discover.lever_api import scrape_lever_all
from discover.ashby_api import scrape_ashby_all
from discover.remoteok import scrape_remoteok
from discover.remote_feeds import scrape_weworkremotely, scrape_remotive
from discover.turing_upwork import scrape_upwork_rss, scrape_turing
from discover.models import JobListing, DiscoveredJobs, TailoredResume, OutreachEmail
from tailor.claude_tailor import tailor_resume, score_match, verify_fidelity
from tailor.pdf_render import render_pdf_inline
from outreach.email_gen import generate_outreach_email
from outreach.contact_finder import discover_contact_emails, get_best_contact
from outreach.tracker import log_application, log_sweep, get_dashboard as tracker_dashboard, _get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Job Agent",
    description="AI-powered job application automation agent. Discovers jobs, tailors resumes, generates outreach emails.",
    version="1.0.0",
)


# ── Request / Response Models ─────────────────────────────

class TailorRequest(BaseModel):
    job_id: str
    job_title: str = ""
    company: str = ""
    job_description: str

class TailorResponse(BaseModel):
    job_id: str
    tailored_resume: dict
    match_score: float
    keywords_matched: list[str]
    pdf_path: Optional[str] = None
    verification: dict = Field(default_factory=dict)

class EmailRequest(BaseModel):
    job_title: str
    company: str
    job_description: str
    tailored_resume: dict
    recipient_name: str = ""
    recipient_role: str = "Hiring Manager"

class EmailResponse(BaseModel):
    subject: str
    body: str

class DailySweepResponse(BaseModel):
    sweep_id: str
    jobs_found: int
    jobs_filtered: int
    resumes_tailored: int
    emails_generated: int
    errors: list[str] = Field(default_factory=list)
    results: list[dict] = Field(default_factory=list)


# ── Endpoints ─────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/discover-jobs", response_model=DiscoveredJobs)
async def discover_jobs(
    sources: str = "yc,greenhouse,github,lever,ashby",
    max_age_days: int = None,
    min_salary_inr: int = None,
):
    """
    Discover fresh job listings from configured sources.

    Query params:
    - sources: comma-separated list of sources (yc, greenhouse)
    - max_age_days: max listing age in days (default from config)
    - min_salary_inr: minimum monthly salary in INR (default from config)
    """
    if max_age_days is None:
        max_age_days = settings.max_listing_age_days
    if min_salary_inr is None:
        min_salary_inr = settings.min_salary_inr

    source_list = [s.strip() for s in sources.split(",")]
    all_jobs: list[JobListing] = []
    errors: list[str] = []

    tasks = []
    if "yc" in source_list:
        tasks.append(("yc", scrape_yc_jobs(
            max_age_days=max_age_days,
            min_salary_inr=min_salary_inr,
            target_locations=settings.target_locations,
        )))
    if "greenhouse" in source_list:
        tasks.append(("greenhouse", scrape_greenhouse_all(
            max_age_days=max_age_days,
            min_salary_inr=min_salary_inr,
            target_locations=settings.target_locations,
        )))
    if "github" in source_list:
        tasks.append(("github", scrape_github()))
    if "lever" in source_list:
        tasks.append(("lever", scrape_lever_all(
            max_age_days=max_age_days,
            target_locations=settings.target_locations,
        )))
    if "ashby" in source_list:
        tasks.append(("ashby", scrape_ashby_all(target_locations=settings.target_locations)))
    if "toptal" in source_list:
        from discover.toptal_scraper import scrape_toptal
        tasks.append(("toptal", scrape_toptal(max_age_days=max_age_days, target_locations=settings.target_locations)))
    if "remoteok" in source_list:
        tasks.append(("remoteok", scrape_remoteok(max_age_days=max_age_days, target_locations=settings.target_locations)))
    if "weworkremotely" in source_list:
        tasks.append(("weworkremotely", scrape_weworkremotely(max_age_days=max_age_days, target_locations=settings.target_locations)))
    if "remotive" in source_list:
        tasks.append(("remotive", scrape_remotive()))
    if "upwork" in source_list:
        tasks.append(("upwork", scrape_upwork_rss()))
    if "turing" in source_list:
        tasks.append(("turing", scrape_turing()))

    for source_name, coro in tasks:
        try:
            jobs = await coro
            all_jobs.extend(jobs)
            logger.info(f"[{source_name}] Found {len(jobs)} matching jobs")
        except Exception as e:
            error_msg = f"[{source_name}] Error: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    # Apply freshness filter
    filtered = [j for j in all_jobs if j.age_days <= max_age_days]

    # Sort by freshness (newest first)
    filtered.sort(key=lambda j: j.posted_date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return DiscoveredJobs(
        source=sources,
        jobs=filtered,
        total_found=len(all_jobs),
        total_filtered=len(filtered),
        errors=errors,
    )


@app.post("/tailor-resume", response_model=TailorResponse)
async def tailor_resume_endpoint(request: TailorRequest):
    """
    Tailor the base resume for a specific job using the configured LLM.

    Returns the tailored resume JSON + match score + PDF path.
    """
    try:
        from tailor.llm import get_llm, reset_provider
        reset_provider()
        get_llm()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}")

    try:
        # 1. Tailor resume
        logger.info(f"Tailoring resume for: {request.job_title} at {request.company}")
        tailored = await tailor_resume(
            base_resume=BASE_RESUME,
            job_description=request.job_description,
            job_title=request.job_title,
            company=request.company,
        )

        # 2. Score match
        score_result = await score_match(
            job_description=request.job_description,
            tailored_resume=tailored,
        )

        # 3. Verify fidelity
        verification = await verify_fidelity(
            base_resume=BASE_RESUME,
            tailored_resume=tailored,
        )

        # 4. Generate PDF
        tailored["metadata"] = {
            "job_id": request.job_id,
            "company": request.company,
            "role": request.job_title,
        }
        pdf_path = await render_pdf_inline(tailored)

        return TailorResponse(
            job_id=request.job_id,
            tailored_resume=tailored,
            match_score=score_result.get("match_score", 0),
            keywords_matched=score_result.get("keywords_matched", []),
            pdf_path=pdf_path,
            verification=verification,
        )

    except Exception as e:
        logger.exception("Resume tailoring failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-email", response_model=EmailResponse)
async def generate_email(request: EmailRequest):
    """Generate a personalized outreach email for a job application."""
    try:
        from tailor.llm import get_llm, reset_provider
        reset_provider()
        get_llm()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}")

    try:
        result = await generate_outreach_email(
            job_title=request.job_title,
            company=request.company,
            job_description=request.job_description,
            tailored_resume=request.tailored_resume,
            recipient_name=request.recipient_name,
            recipient_role=request.recipient_role,
        )
        return EmailResponse(**result)

    except Exception as e:
        logger.exception("Email generation failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/daily-sweep", response_model=DailySweepResponse)
async def daily_sweep(
    sources: str = "yc,greenhouse,github,lever,ashby,remoteok,weworkremotely,remotive",
    max_jobs: int = 10,
    tailor: bool = True,
    generate_emails: bool = True,
):
    """
    Full daily pipeline: discover → tailor → generate outreach emails.

    This is the endpoint that n8n calls on a schedule.

    Query params:
    - sources: which job sources to scan
    - max_jobs: max jobs to process (limit API costs)
    - tailor: whether to tailor resumes
    - generate_emails: whether to generate outreach emails
    """
    sweep_id = f"sweep-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    errors: list[str] = []
    results: list[dict] = []

    # 1. Discover jobs
    try:
        discovered = await discover_jobs(sources=sources)
        # Interleave by source for diversity — avoids all-Ashby sweeps
        by_source: dict[str, list] = {}
        for j in discovered.jobs:
            by_source.setdefault(j.source, []).append(j)
        interleaved = []
        max_per_source = max(len(v) for v in by_source.values()) if by_source else 0
        for i in range(max_per_source):
            for source_jobs in by_source.values():
                if i < len(source_jobs):
                    interleaved.append(source_jobs[i])
        # Also deduplicate by company
        seen_companies = set()
        deduped = []
        for j in interleaved:
            if j.company.lower() not in seen_companies:
                seen_companies.add(j.company.lower())
                deduped.append(j)
        jobs = deduped[:max_jobs]
        logger.info(f"Daily sweep [{sweep_id}]: Found {len(jobs)} jobs to process (interleaved from {list(by_source.keys())})")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Job discovery failed: {e}")

    if not jobs:
        return DailySweepResponse(
            sweep_id=sweep_id,
            jobs_found=0,
            jobs_filtered=0,
            resumes_tailored=0,
            emails_generated=0,
            errors=["No matching jobs found"],
        )

    tailored_count = 0
    email_count = 0
    skipped_dedup = 0

    from outreach.tracker import was_emailed_recently, mark_emailed

    for job in jobs:
        if was_emailed_recently(job.company, days=14):
            skipped_dedup += 1
            results.append({
                "job_id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "source": job.source,
                "skipped": "already_emailed_within_14_days",
            })
            continue

        result_entry = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "match_score": 0,
            "pdf_path": None,
            "email_subject": None,
            "error": None,
        }

        try:
            if tailor:
                tailored_result = await tailor_resume_endpoint(TailorRequest(
                    job_id=job.id,
                    job_title=job.title,
                    company=job.company,
                    job_description=job.description,
                ))
                result_entry["match_score"] = tailored_result.match_score
                result_entry["pdf_path"] = tailored_result.pdf_path
                tailored_count += 1

                email_body = ""
                email_subject = ""
                if generate_emails:
                    email_result = await generate_email(EmailRequest(
                        job_title=job.title,
                        company=job.company,
                        job_description=job.description,
                        tailored_resume=tailored_result.tailored_resume,
                    ))
                    result_entry["email_subject"] = email_result.subject
                    result_entry["email_body"] = email_result.body[:200]
                    email_subject = email_result.subject
                    email_body = email_result.body
                    email_count += 1

                    # Auto-send via Gmail if credentials available
                    try:
                        from outreach.google_auth import send_email

                        contacts = await discover_contact_emails(job.company, job.url)
                        best = get_best_contact(contacts, prefer_role="careers")
                        recipient = best.get("email", "") if best.get("email") else settings.sender_email
                        recipient_name = best.get("name", "") if best.get("name") else "Hiring Team"

                        full_body = f"{email_body}\n\n---\nApplied for: {job.title} at {job.company}\n{job.url}"
                        attachment = result_entry.get("pdf_path", "") or ""
                        attachment_arg = ""
                        if attachment:
                            pdf_path = Path(attachment)
                            if not pdf_path.is_absolute():
                                pdf_path = Path(__file__).parent / attachment
                                if not pdf_path.exists():
                                    pdf_path = Path(settings.output_dir) / Path(attachment).name
                            if pdf_path.exists():
                                attachment_arg = str(pdf_path)
                                logger.info(f"Attaching PDF: {attachment_arg} ({pdf_path.stat().st_size} bytes)")
                            else:
                                logger.warning(f"PDF not found: tried {pdf_path}")
                        else:
                            attachment_arg = ""

                        send_email(recipient, email_subject, full_body, attachment_path=attachment_arg)
                        mark_emailed(job.id, recipient)

                        result_entry["email_sent"] = True
                        result_entry["contact_email"] = recipient
                        logger.info(f"Email sent to {recipient} for {job.company}" + (" (with PDF)" if attachment_arg else ""))
                    except Exception as e:
                        logger.warning(f"Gmail send skipped: {e}")

                log_application(
                    job_id=job.id,
                    company=job.company,
                    role=job.title,
                    location=job.location,
                    source=job.source,
                    url=job.url,
                    match_score=tailored_result.match_score,
                    resume_pdf=tailored_result.pdf_path or "",
                    email_subject=email_subject,
                    email_body=email_body,
                    status="tailored",
                )

        except Exception as e:
            error_msg = f"Failed processing {job.id}: {e}"
            logger.error(error_msg)
            result_entry["error"] = str(e)
            errors.append(error_msg)

        results.append(result_entry)

    log_sweep(sweep_id, len(jobs), tailored_count, email_count, errors)

    if settings.tracking_sheet_id:
        try:
            from outreach.google_auth import sync_to_sheet
            conn = _get_db()
            rows = conn.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
            conn.close()
            apps = [dict(r) for r in rows]
            synced = sync_to_sheet(settings.tracking_sheet_id, apps)
            logger.info(f"Synced {synced} rows to Google Sheets")
        except Exception as e:
            logger.warning(f"Sheet sync skipped: {e}")

    return DailySweepResponse(
        sweep_id=sweep_id,
        jobs_found=len(jobs),
        jobs_filtered=discovered.total_filtered,
        resumes_tailored=tailored_count,
        emails_generated=email_count,
        errors=errors,
        results=results,
    )


@app.get("/download-pdf")
async def download_pdf(path: str):
    """Download a generated resume PDF."""
    full_path = Path(path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=full_path.name,
    )


@app.get("/dashboard")
async def dashboard():
    return tracker_dashboard()


@app.post("/track/{job_id}")
async def update_tracking(job_id: str, status: str = "applied", notes: str = ""):
    from outreach.tracker import update_status
    update_status(job_id, status, notes)
    return {"ok": True, "job_id": job_id, "status": status}


@app.post("/sync-sheets")
async def sync_to_sheets():
    if not settings.tracking_sheet_id:
        raise HTTPException(status_code=400, detail="TRACKING_SHEET_ID not set in .env")

    conn = _get_db()
    rows = conn.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
    conn.close()

    from outreach.google_auth import sync_to_sheet
    apps = [dict(r) for r in rows]
    updated = sync_to_sheet(settings.tracking_sheet_id, apps)
    return {"ok": True, "synced": len(apps), "rows_updated": updated}


# ── Startup ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
