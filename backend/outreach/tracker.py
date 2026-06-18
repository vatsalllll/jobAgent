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
            status TEXT DEFAULT 'discovered',
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
    status: str = "discovered",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute("""
        INSERT INTO applications (id, company, role, location, source, url, match_score,
            resume_pdf, email_subject, email_body, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            match_score = excluded.match_score,
            resume_pdf = COALESCE(excluded.resume_pdf, applications.resume_pdf),
            email_subject = COALESCE(excluded.email_subject, applications.email_subject),
            email_body = COALESCE(excluded.email_body, applications.email_body),
            status = excluded.status,
            updated_at = excluded.updated_at
    """, (job_id, company, role, location, source, url, match_score,
          resume_pdf, email_subject, email_body, status, now, now))
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
    elif status in ("responded", "rejected", "interview"):
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
        "UPDATE applications SET emailed_at = ?, contact_email = ?, status = CASE WHEN status = 'discovered' OR status = 'tailored' THEN 'emailed' ELSE status END, updated_at = ? WHERE id = ?",
        (now, contact_email, now, job_id),
    )
    conn.commit()
    conn.close()
