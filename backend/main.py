import json
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Depends
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
from discover.hackernews import scrape_hackernews_jobs
from discover.indeed_rss import scrape_indeed_jobs
from discover.smartrecruiters import scrape_smartrecruiters
from discover.workable import scrape_workable
from discover.recruitee import scrape_recruitee
from discover.teamtailor import scrape_teamtailor
from discover.themuse import scrape_themuse
from discover.himalayas import scrape_himalayas
from discover.adzuna import scrape_adzuna
from discover.india_sitemaps import scrape_cutshort, scrape_hirist, scrape_foundit
from discover.models import JobListing, DiscoveredJobs, TailoredResume, OutreachEmail
from tailor.claude_tailor import tailor_resume, score_match, verify_fidelity
from tailor.pdf_render import render_pdf_inline
from outreach.email_gen import generate_outreach_email
from outreach.contact_finder import discover_company_info, get_best_contact, _is_ats_domain, should_send
from outreach.email_verify import verify_email_before_send
from outreach.email_monitor import check_all_applications
from outreach.tracker import log_application, log_sweep, get_dashboard as tracker_dashboard, _get_db, mark_emailed, was_emailed_recently, was_job_emailed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Job Agent",
    description="AI-powered job application automation agent. Discovers jobs, tailors resumes, generates outreach emails.",
    version="1.1.0",
)


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=401, detail="API_KEY not configured. Set it in .env to protect this endpoint.")
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


_DEV_SIGNALS = [
    "software", "engineer", "developer", "backend", "back end", "frontend", "front end",
    "full stack", "full-stack", "sde", "swe", "programmer", "devops", "sre", "platform",
    "infrastructure", "data engineer", "ml engineer", "machine learning engineer", "ai engineer",
    "applied ai", "applied ml", "web developer", "mobile developer", "ios", "android",
]
_NON_DEV_ROLES = [
    "artist", "designer", "ux ", "ui/ux", "graphic", "illustrat", "writer", "copywriter",
    "content", "brand", "marketing", "sales", "account executive", "recruiter",
    "talent acquisition", "community", "customer success", "customer support", "video",
    "animator", "photographer", "social media", " seo", "editor", "3d ", "game artist",
    "voice", "translator", "operador", "portaria", "vagas",
]


def _is_relevant_role(title: str) -> bool:
    """Deterministically keep only software-engineering roles. Rejects non-dev 'AI' roles
    (AI artist, designer, brand, marketing, …) that the LLM match-score can over-rate."""
    t = (title or "").lower()
    if any(n in t for n in _NON_DEV_ROLES):
        return False
    return any(d in t for d in _DEV_SIGNALS)


def _resolve_pdf_path(attachment: str) -> str:
    """Resolve a (possibly relative) tailored-PDF path to an absolute path, or '' if missing."""
    if not attachment:
        return ""
    pdf_path = Path(attachment)
    if not pdf_path.is_absolute():
        candidate = Path(__file__).parent / attachment
        pdf_path = candidate if candidate.exists() else Path(settings.output_dir) / Path(attachment).name
    return str(pdf_path) if pdf_path.exists() else ""


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


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/discover-jobs", response_model=DiscoveredJobs)
async def discover_jobs(
    sources: str = "yc,greenhouse,github,lever,ashby,smartrecruiters,workable,recruitee,teamtailor,themuse,himalayas,remoteok,remotive,weworkremotely,hackernews,cutshort,hirist,foundit",
    max_age_days: int = None,
    min_salary_inr: int = None,
):
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
        tasks.append(("github", scrape_github(
            max_age_days=max_age_days,
            target_locations=settings.target_locations,
            min_salary_inr=min_salary_inr,
        )))
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
    if "hackernews" in source_list:
        tasks.append(("hackernews", scrape_hackernews_jobs(
            max_age_days=max_age_days,
            target_locations=settings.target_locations,
        )))
    if "indeed" in source_list:
        tasks.append(("indeed", scrape_indeed_jobs(
            max_age_days=max_age_days,
            target_locations=settings.target_locations,
        )))
    # ── New free sources (ATS boards, aggregators, India) ──
    _new_sources = {
        "smartrecruiters": scrape_smartrecruiters,
        "workable": scrape_workable,
        "recruitee": scrape_recruitee,
        "teamtailor": scrape_teamtailor,
        "themuse": scrape_themuse,
        "himalayas": scrape_himalayas,
        "adzuna": scrape_adzuna,
        "cutshort": scrape_cutshort,
        "hirist": scrape_hirist,
        "foundit": scrape_foundit,
    }
    for _name, _fn in _new_sources.items():
        if _name in source_list:
            tasks.append((_name, _fn(
                max_age_days=max_age_days,
                target_locations=settings.target_locations,
                min_salary_inr=min_salary_inr,
            )))

    for source_name, coro in tasks:
        try:
            jobs = await coro
            all_jobs.extend(jobs)
            logger.info(f"[{source_name}] Found {len(jobs)} matching jobs")
        except Exception as e:
            error_msg = f"[{source_name}] Error: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    filtered = [j for j in all_jobs if j.age_days <= max_age_days]
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
    try:
        from tailor.llm import get_llm, reset_provider
        reset_provider()
        get_llm()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}")

    try:
        logger.info(f"Tailoring resume for: {request.job_title} at {request.company}")
        tailored = await tailor_resume(
            base_resume=BASE_RESUME,
            job_description=request.job_description,
            job_title=request.job_title,
            company=request.company,
        )

        score_result = await score_match(
            job_description=request.job_description,
            tailored_resume=tailored,
        )

        verification = await verify_fidelity(
            base_resume=BASE_RESUME,
            tailored_resume=tailored,
        )

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
    sources: str = "yc,greenhouse,github,lever,ashby,smartrecruiters,workable,recruitee,teamtailor,themuse,himalayas,remoteok,remotive,weworkremotely,hackernews,cutshort,hirist,foundit",
    max_jobs: int = 6,
    tailor: bool = True,
    generate_emails: bool = True,
    _: None = Depends(verify_api_key),
):
    sweep_id = f"sweep-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    errors: list[str] = []
    results: list[dict] = []

    try:
        discovered = await discover_jobs(sources=sources)

        # Keep only software-engineering roles (drops AI-artist/designer/marketing/etc. noise).
        before = len(discovered.jobs)
        discovered.jobs = [j for j in discovered.jobs if _is_relevant_role(j.title)]
        logger.info(f"Relevance filter: kept {len(discovered.jobs)}/{before} software-engineering roles")

        source_counts = {}
        for j in discovered.jobs:
            source_counts[j.source] = source_counts.get(j.source, 0) + 1
        logger.info(f"Daily sweep [{sweep_id}]: Source breakdown: {source_counts}")

        by_source: dict[str, list] = {}
        for j in discovered.jobs:
            by_source.setdefault(j.source, []).append(j)

        yc_jobs = by_source.pop("yc", [])
        remaining = []
        max_per_source = max(len(v) for v in by_source.values()) if by_source else 0
        for i in range(max_per_source):
            for source_jobs in by_source.values():
                if i < len(source_jobs):
                    remaining.append(source_jobs[i])

        seen = set()
        deduped = []
        for j in yc_jobs + remaining:
            key = f"{j.company.lower()}|{j.title.lower()}"
            if key not in seen:
                seen.add(key)
                deduped.append(j)

        jobs = deduped[:max_jobs]
        logger.info(f"Daily sweep [{sweep_id}]: Processing {len(jobs)} jobs (YC: {len([j for j in jobs if j.source == 'yc'])}, others: {len([j for j in jobs if j.source != 'yc'])})")
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

    # Load the set of already-emailed job keys from the Google Sheet (persists across Render
    # restarts, unlike the ephemeral SQLite) so we never email the same job description twice.
    sheet_keys: set = set()
    if settings.tracking_sheet_id:
        try:
            from outreach.google_auth import get_emailed_keys
            sheet_keys = get_emailed_keys(settings.tracking_sheet_id)
            logger.info(f"Loaded {len(sheet_keys)} already-emailed job keys from Sheet for dedup")
        except Exception as e:
            logger.warning(f"Could not load emailed keys from Sheet: {e}")

    for job in jobs:
        is_yc = job.source == "yc"

        # Per-JOB dedup (not per-company): the same posting is never emailed twice, but a
        # different role at the same company is still allowed.
        if not is_yc and was_job_emailed(job.id, job.url, job.company, job.title, sheet_keys):
            skipped_dedup += 1
            results.append({
                "job_id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "source": job.source,
                "skipped": "already_emailed_this_job",
            })
            continue

        result_entry = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "is_yc": is_yc,
            "match_score": 0,
            "pdf_path": None,
            "email_subject": None,
            "error": None,
        }

        try:
            company_info = await discover_company_info(job.company, job.url)
            best_contact = get_best_contact(company_info["contacts"])
            linkedin_contacts = company_info.get("linkedin_contacts", [])
            careers_page = company_info.get("careers_page", "")
            linkedin_str = ", ".join([f"{c['name']} ({c['linkedin_url']})" for c in linkedin_contacts[:2]]) if linkedin_contacts else ""

            if is_yc:
                result_entry["action"] = "logged_for_manual_apply"
                log_application(
                    job_id=job.id,
                    company=job.company,
                    role=job.title,
                    location=job.location,
                    source=job.source,
                    url=job.url,
                    match_score=0,
                    linkedin_contact=linkedin_str,
                    careers_page=careers_page,
                    status="pending_manual_apply",
                    is_yc=True,
                    notes=f"YC company. Apply manually. LinkedIn: {linkedin_str}. Careers: {careers_page}",
                )
                logger.info(f"YC company logged for manual apply: {job.company}")
                results.append(result_entry)
                continue

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

                # FIDELITY GATE — never email a resume that failed fact-checking (fails closed).
                verification = getattr(tailored_result, "verification", {}) or {}
                is_faithful = bool(verification.get("is_faithful", False))
                result_entry["fidelity_ok"] = is_faithful

                # SEND GATE — only email a safe, deliverable contact on a real (non-guessed) domain.
                domain_guessed = company_info.get("domain_guessed", False)
                ok_to_send, send_reason = should_send(best_contact, domain_guessed)
                recipient = best_contact.get("email", "") or ""

                email_body = ""
                email_subject = ""
                application_status = "tailored"
                result_entry["email_sent"] = False
                result_entry["contact_email"] = ""

                if generate_emails:
                    recipient_name = best_contact.get("name") or "Hiring Team"
                    recipient_position = best_contact.get("position") or "Hiring Team"
                    is_founder = any(k in recipient_position.lower() for k in ["founder", "ceo", "cto", "chief"])

                    email_result = await generate_outreach_email(
                        job_title=job.title,
                        company=job.company,
                        job_description=job.description,
                        tailored_resume=tailored_result.tailored_resume,
                        recipient_name=recipient_name,
                        recipient_role=recipient_position,
                        is_founder=is_founder,
                    )
                    email_subject = email_result["subject"]
                    email_body = email_result["body"]
                    result_entry["email_subject"] = email_subject
                    result_entry["email_body"] = email_body[:200]
                    email_count += 1

                    if tailored_result.match_score < settings.min_match_score:
                        result_entry["skipped_send"] = f"low_match_score ({tailored_result.match_score} < {settings.min_match_score})"
                        application_status = "low_match"
                        logger.info(f"Skipping {job.company} — match {tailored_result.match_score} below {settings.min_match_score} (likely mis-targeted job)")
                    elif not is_faithful:
                        result_entry["skipped_send"] = "fidelity_failed"
                        application_status = "needs_review"
                        logger.warning(f"Fidelity check failed for {job.company} — NOT sending. Issues: {verification.get('issues')}")
                    elif not ok_to_send:
                        result_entry["skipped_send"] = send_reason
                        application_status = "missing_contact"
                        logger.info(f"Not sending for {job.company}: {send_reason}")
                    elif not verify_email_before_send(recipient):
                        result_entry["skipped_send"] = "email_unverified_mx"
                        application_status = "missing_contact"
                        logger.warning(f"MX/verify failed for {recipient} — not sending for {job.company}")
                    else:
                        attachment_arg = _resolve_pdf_path(result_entry.get("pdf_path", "") or "")
                        try:
                            from outreach.google_auth import send_email
                            full_body = f"{email_body}\n\n---\nApplied for: {job.title} at {job.company}\n{job.url}"
                            send_email(recipient, email_subject, full_body, attachment_path=attachment_arg)
                            mark_emailed(job.id, recipient)
                            result_entry["email_sent"] = True
                            result_entry["contact_email"] = recipient
                            application_status = "ongoing"
                            logger.info(f"Email sent to {recipient} for {job.company}" + (" (with PDF)" if attachment_arg else " (no PDF)"))
                        except Exception as e:
                            logger.warning(f"Gmail send failed for {job.company}: {e}")
                            result_entry["error"] = str(e)
                            application_status = "send_failed"

                # Record contact_email ONLY when actually sent, so dedup never treats an
                # un-sent job as already-emailed.
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
                    contact_email=(recipient if result_entry.get("email_sent") else ""),
                    linkedin_contact=linkedin_str,
                    careers_page=careers_page,
                    status=application_status,
                    is_yc=False,
                    notes=(f"Best contact (not emailed): {best_contact.get('email')}" if not result_entry.get("email_sent") and best_contact.get("email") else ""),
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
async def download_pdf(path: str, _: None = Depends(verify_api_key)):
    allowed_dir = Path(settings.output_dir).resolve()
    full_path = Path(path).resolve()
    if not str(full_path).startswith(str(allowed_dir)):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed directory")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=full_path.name,
    )


@app.get("/dashboard")
async def dashboard(_: None = Depends(verify_api_key)):
    return tracker_dashboard()


@app.post("/track/{job_id}")
async def update_tracking(job_id: str, status: str = "applied", notes: str = "", _: None = Depends(verify_api_key)):
    from outreach.tracker import update_status
    update_status(job_id, status, notes)
    return {"ok": True, "job_id": job_id, "status": status}


@app.post("/sync-sheets")
async def sync_to_sheets(_: None = Depends(verify_api_key)):
    if not settings.tracking_sheet_id:
        raise HTTPException(status_code=400, detail="TRACKING_SHEET_ID not set in .env")

    conn = _get_db()
    rows = conn.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
    conn.close()

    from outreach.google_auth import sync_to_sheet
    apps = [dict(r) for r in rows]
    updated = sync_to_sheet(settings.tracking_sheet_id, apps)
    return {"ok": True, "synced": len(apps), "rows_updated": updated}


@app.post("/check-emails")
async def check_emails(_: None = Depends(verify_api_key)):
    """Check Gmail inbox for replies and auto-update application statuses."""
    try:
        result = await check_all_applications()

        if settings.tracking_sheet_id:
            try:
                from outreach.google_auth import sync_to_sheet
                conn = _get_db()
                rows = conn.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
                conn.close()
                apps = [dict(r) for r in rows]
                sync_to_sheet(settings.tracking_sheet_id, apps)
            except Exception as e:
                logger.warning(f"Sheet sync after email check skipped: {e}")

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email check failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
