import os
import json
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CREDS_PATH = Path(__file__).parent.parent / "data" / "google_credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "data" / "google_token.pickle"


def get_credentials() -> Credentials:
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
        creds.refresh(Request())
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

    return creds


def get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def get_gmail_service():
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def sync_to_sheet(spreadsheet_id: str, applications: list[dict]) -> int:
    service = get_sheets_service()
    sheet_name = "Applications"

    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing_sheets = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

    if sheet_name not in existing_sheets:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()

    headers = [
        "Date", "Company", "Role", "Location", "Source", "Match Score",
        "Email Subject", "Status", "Contact", "URL", "Resume PDF", "Notes"
    ]

    values = [headers]
    for app in applications:
        values.append([
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
            app.get("notes", ""),
        ])

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A:Z",
    ).execute()

    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    return result.get("updatedRows", 0)


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
