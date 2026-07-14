import asyncio
import re
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional

from outreach.google_auth import get_gmail_service
from outreach.tracker import update_status, _get_db
from outreach.google_search import classify_email


def _decode_base64(data: str) -> str:
    """Decode base64url encoded string."""
    try:
        decoded = base64.urlsafe_b64decode(data.encode("ASCII"))
        return decoded.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    if "body" in payload and "data" in payload["body"]:
        return _decode_base64(payload["body"]["data"])

    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                return _decode_base64(part.get("body", {}).get("data", ""))
            elif mime == "multipart/alternative" and "parts" in part:
                for subpart in part["parts"]:
                    if subpart.get("mimeType") == "text/plain":
                        return _decode_base64(subpart.get("body", {}).get("data", ""))

    return ""


def _get_headers(msg: dict) -> dict:
    """Extract headers from Gmail message."""
    headers = {}
    for h in msg.get("payload", {}).get("headers", []):
        headers[h.get("name", "").lower()] = h.get("value", "")
    return headers


async def check_email_replies(hours_back: int = 48) -> list[dict]:
    """
    Check Gmail inbox for replies to job applications in the last N hours.
    Returns list of updates: [{job_id, company, status, subject, snippet}]
    """
    try:
        service = get_gmail_service()
    except Exception:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y/%m/%d")

    query = f"in:inbox after:{cutoff}"
    try:
        results = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        messages = results.get("messages", [])
    except Exception:
        return []

    updates = []

    for msg_meta in messages:
        msg_id = msg_meta["id"]
        try:
            msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        except Exception:
            continue

        headers = _get_headers(msg)
        subject = headers.get("subject", "")
        from_email = headers.get("from", "")
        body = _extract_body(msg.get("payload", {}))
        is_reply = bool(headers.get("in-reply-to") or headers.get("references"))

        classification = classify_email(subject, body)
        if classification == "unknown":
            continue

        # Extract the sender's email domain for precise matching.
        m = re.search(r"[\w.+-]+@([\w.-]+)", from_email)
        from_domain = m.group(1).lower() if m else ""

        conn = _get_db()
        rows = conn.execute(
            "SELECT id, company, contact_email FROM applications WHERE contact_email IS NOT NULL AND contact_email != '' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()

        matched_job = None
        # 1) Strongest: the sender's domain matches a contact we actually emailed.
        if from_domain:
            for row in rows:
                contact = (row["contact_email"] or "").lower()
                if "@" in contact and contact.split("@")[1] == from_domain:
                    matched_job = dict(row)
                    break
        # 2) Fallback: only trust a company-name match when the message is a genuine reply
        #    (threaded via In-Reply-To/References), to avoid random inbox mail flipping status.
        if not matched_job and is_reply:
            for row in rows:
                company = (row["company"] or "").lower()
                if company and (company in subject.lower() or company in from_email.lower()):
                    matched_job = dict(row)
                    break

        if matched_job:
            job_id = matched_job["id"]
            company = matched_job["company"]

            update_status(job_id, classification, f"Auto-detected from email: {subject}")

            updates.append({
                "job_id": job_id,
                "company": company,
                "status": classification,
                "subject": subject,
                "snippet": body[:200] if body else "",
            })

    return updates


async def check_all_applications() -> dict:
    """Run full email monitoring cycle and return summary."""
    updates = await check_email_replies(hours_back=48)

    rejected = [u for u in updates if u["status"] == "rejected"]
    second_round = [u for u in updates if u["status"] == "second_round"]

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_updates": len(updates),
        "rejected": len(rejected),
        "second_round": len(second_round),
        "updates": updates,
    }
