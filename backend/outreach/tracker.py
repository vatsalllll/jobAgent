import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "data" / "tracker.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            location TEXT,
            source TEXT,
            url TEXT,
            match_score REAL DEFAULT 0,
            resume_pdf TEXT,
            email_subject TEXT,
            email_body TEXT,
            contact_email TEXT,
            linkedin_contact TEXT,
            careers_page TEXT,
            status TEXT DEFAULT 'discovered',
            is_yc INTEGER DEFAULT 0,
            applied_date TEXT,
            response_date TEXT,
            follow_up_date TEXT,
            emailed_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sweeps (
            id TEXT PRIMARY KEY,
            jobs_found INTEGER,
            resumes_tailored INTEGER,
            emails_generated INTEGER,
            errors TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def log_application(
    job_id: str,
    company: str,
    role: str,
    location: str = "",
    source: str = "",
    url: str = "",
    match_score: float = 0,
    resume_pdf: str = "",
    email_subject: str = "",
    email_body: str = "",
    contact_email: str = "",
    linkedin_contact: str = "",
    careers_page: str = "",
    status: str = "discovered",
    is_yc: bool = False,
    notes: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute("""
        INSERT INTO applications (id, company, role, location, source, url, match_score,
            resume_pdf, email_subject, email_body, contact_email, linkedin_contact, careers_page,
            status, is_yc, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            match_score = excluded.match_score,
            resume_pdf = COALESCE(excluded.resume_pdf, applications.resume_pdf),
            email_subject = COALESCE(excluded.email_subject, applications.email_subject),
            email_body = COALESCE(excluded.email_body, applications.email_body),
            contact_email = COALESCE(excluded.contact_email, applications.contact_email),
            linkedin_contact = COALESCE(excluded.linkedin_contact, applications.linkedin_contact),
            careers_page = COALESCE(excluded.careers_page, applications.careers_page),
            status = excluded.status,
            is_yc = excluded.is_yc,
            notes = COALESCE(excluded.notes, applications.notes),
            updated_at = excluded.updated_at
    """, (job_id, company, role, location, source, url, match_score,
          resume_pdf, email_subject, email_body, contact_email, linkedin_contact, careers_page,
          status, 1 if is_yc else 0, notes, now, now))
    conn.commit()
    conn.close()


def log_sweep(sweep_id: str, jobs_found: int, tailored: int, emails: int, errors: list[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        "INSERT INTO sweeps (id, jobs_found, resumes_tailored, emails_generated, errors, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (sweep_id, jobs_found, tailored, emails, json.dumps(errors), now),
    )
    conn.commit()
    conn.close()


def update_status(job_id: str, status: str, notes: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    updates = {"status": status, "updated_at": now}
    if status == "applied":
        updates["applied_date"] = now
    elif status in ("responded", "rejected", "interview", "second_round"):
        updates["response_date"] = now
    if notes:
        updates["notes"] = notes

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE applications SET {set_clause} WHERE id = ?", (*updates.values(), job_id))
    conn.commit()
    conn.close()


def get_dashboard() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) as n FROM applications").fetchone()["n"]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as n FROM applications GROUP BY status"
    ).fetchall()
    by_yc = conn.execute(
        "SELECT is_yc, COUNT(*) as n FROM applications GROUP BY is_yc"
    ).fetchall()
    recent = conn.execute(
        "SELECT * FROM applications ORDER BY updated_at DESC LIMIT 20"
    ).fetchall()
    sweeps = conn.execute(
        "SELECT * FROM sweeps ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    conn.close()

    return {
        "total_applications": total,
        "by_status": {row["status"]: row["n"] for row in by_status},
        "by_yc": {"yc" if row["is_yc"] else "non_yc": row["n"] for row in by_yc},
        "recent": [dict(row) for row in recent],
        "recent_sweeps": [dict(row) for row in sweeps],
    }


def was_emailed_recently(company: str, days: int = 14) -> bool:
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = _get_db()
    row = conn.execute(
        "SELECT emailed_at FROM applications WHERE company = ? AND emailed_at >= ? LIMIT 1",
        (company, cutoff),
    ).fetchone()
    conn.close()
    return row is not None


def mark_emailed(job_id: str, contact_email: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        "UPDATE applications SET emailed_at = ?, contact_email = ?, status = CASE WHEN status = 'discovered' OR status = 'tailored' OR status = 'pending_manual_apply' THEN 'ongoing' ELSE status END, updated_at = ? WHERE id = ?",
        (now, contact_email, now, job_id),
    )
    conn.commit()
    conn.close()


def get_pending_applications() -> list[dict]:
    """Get applications that are awaiting manual apply (YC companies)."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM applications WHERE status = 'pending_manual_apply' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ongoing_applications() -> list[dict]:
    """Get applications with status 'ongoing' for email monitoring."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM applications WHERE status = 'ongoing' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
