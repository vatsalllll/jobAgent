import os
import json
import pickle
from pathlib import Path
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDS_PATH = Path(__file__).parent.parent / "data" / "google_credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "data" / "google_token.pickle"


_cached_creds: Optional[Credentials] = None


def get_credentials() -> Credentials:
    global _cached_creds
    # Reuse a still-valid token instead of refreshing on every send/sync (avoids a
    # network round-trip per email and Google rate limits).
    if _cached_creds is not None and _cached_creds.valid:
        return _cached_creds

    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

    if refresh_token and client_id and client_secret:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        try:
            creds.refresh(Request())
        except Exception as e:
            raise RuntimeError(
                f"Google token refresh failed (revoked/expired refresh token?): {e}"
            ) from e
        _cached_creds = creds
        return creds

    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"OAuth credentials not found at {CREDS_PATH}.\n"
                    "Download them from https://console.cloud.google.com/apis/credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    _cached_creds = creds
    return creds


def get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def get_gmail_service():
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def _ensure_sheet(service, spreadsheet_id: str, sheet_name: str):
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing_sheets = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

    if sheet_name not in existing_sheets:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()


def _app_to_row(app: dict) -> list:
    return [
        app.get("created_at", "")[:10],
        app.get("company", ""),
        app.get("role", ""),
        app.get("location", ""),
        app.get("source", ""),
        app.get("match_score", 0),
        app.get("email_subject", ""),
        app.get("status", ""),
        app.get("contact_email", ""),
        app.get("url", ""),
        app.get("resume_pdf", ""),
        "YES" if app.get("is_yc") else "NO",
        app.get("linkedin_contact", ""),
        app.get("careers_page", ""),
        app.get("emailed_at", "")[:10] if app.get("emailed_at") else "",
        app.get("notes", ""),
    ]


def sync_to_sheet(spreadsheet_id: str, applications: list[dict]) -> int:
    service = get_sheets_service()
    sheet_name = "Applications"

    _ensure_sheet(service, spreadsheet_id, sheet_name)

    headers = [
        "Date", "Company", "Role", "Location", "Source", "Match Score",
        "Email Subject", "Status", "Contact", "URL", "Resume PDF",
        "Is YC?", "LinkedIn Contact", "Careers Page", "Emailed At", "Notes"
    ]

    # Read existing data
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A1:Z1000",
    ).execute()
    existing_rows = result.get("values", [])

    # Ensure headers exist
    if not existing_rows or existing_rows[0] != headers:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()
        existing_rows = [headers]

    # Build set of existing company+role keys (column B + C, 1-indexed)
    existing_keys = set()
    for row in existing_rows[1:]:
        if len(row) >= 3:
            key = f"{row[1]}|{row[2]}"
            existing_keys.add(key)

    # Append only new applications
    new_rows = []
    for app in applications:
        key = f"{app.get('company', '')}|{app.get('role', '')}"
        if key not in existing_keys:
            new_rows.append(_app_to_row(app))
            existing_keys.add(key)

    if new_rows:
        start_row = len(existing_rows) + 1
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A{start_row}",
            valueInputOption="RAW",
            body={"values": new_rows},
        ).execute()

    return len(new_rows)


def get_emailed_keys(spreadsheet_id: str) -> set:
    """Read the tracking Sheet and return the set of dedup keys for jobs already emailed.

    This is the persistence layer that survives Render's ephemeral disk: even after the
    local SQLite is wiped, the Sheet remembers what was already contacted so we never
    email the same job twice.
    """
    from outreach.tracker import emailed_keys_from_rows

    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="'Applications'!A2:P5000",
        ).execute()
    except Exception:
        return set()

    rows = []
    for r in result.get("values", []):
        def col(i):
            return r[i] if len(r) > i else ""
        rows.append({
            "company": col(1),
            "role": col(2),
            "status": col(7),
            "contact_email": col(8),
            "url": col(9),
            "emailed_at": col(14),
        })
    return emailed_keys_from_rows(rows)


def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> dict:
    import base64
    from email.message import EmailMessage
    from pathlib import Path
    from mimetypes import guess_type

    service = get_gmail_service()

    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject

    if attachment_path:
        path = Path(attachment_path)
        if path.exists() and path.is_file():
            mime_type, _ = guess_type(str(path))
            if mime_type is None:
                mime_type = "application/octet-stream"
            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me",
        body={"raw": encoded},
    ).execute()

    return result
