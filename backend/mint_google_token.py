"""One-off helper: mint a fresh Google OAuth refresh token for job-agent.

Why: Render's GOOGLE_REFRESH_TOKEN went invalid (`invalid_grant`), which blocks Gmail
sending and Sheets sync. This opens a browser, you consent with your SENDER Gmail account,
and it prints a new refresh token to paste into Render's GOOGLE_REFRESH_TOKEN.

Run it locally (a browser is required):

    cd backend
    GOOGLE_CLIENT_ID='<from Render>' GOOGLE_CLIENT_SECRET='<from Render>' \
      venv/bin/python mint_google_token.py

(Reveal GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET on Render → Environment. Alternatively,
drop your OAuth client-secret JSON at data/google_credentials.json and run without the env vars.)

IMPORTANT: Publish your OAuth consent screen to "In production" first, or the new token
expires again in ~7 days (Testing-mode limit).
"""
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDS_FILE = Path(__file__).parent / "data" / "google_credentials.json"


def _flow() -> InstalledAppFlow:
    cid = os.getenv("GOOGLE_CLIENT_ID")
    csecret = os.getenv("GOOGLE_CLIENT_SECRET")
    if cid and csecret:
        return InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": cid,
                    "client_secret": csecret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            },
            SCOPES,
        )
    if CREDS_FILE.exists():
        return InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    raise SystemExit(
        "Provide GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET env vars, or place your OAuth "
        f"client-secret JSON at {CREDS_FILE}."
    )


def main():
    flow = _flow()
    # access_type=offline + prompt=consent forces Google to return a refresh token.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print("\n" + "=" * 60)
    print("SUCCESS — paste this into Render's GOOGLE_REFRESH_TOKEN:")
    print("=" * 60)
    print(creds.refresh_token)
    print("=" * 60)
    print("(These should match what's already on Render:)")
    print("GOOGLE_CLIENT_ID     =", creds.client_id)
    print("GOOGLE_CLIENT_SECRET =", (creds.client_secret or "")[:6] + "…")


if __name__ == "__main__":
    main()
