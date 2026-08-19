"""One-time Gmail OAuth setup to obtain GMAIL_REFRESH_TOKEN.

Prerequisites:
1. Google Cloud project with Gmail API enabled
2. OAuth client ID (Desktop app) from Google Cloud Console
3. Add GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET to Backend/.env

Usage:
  cd Backend
  pip install google-auth-oauthlib
  python scripts/gmail_authorize.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("Add these to Backend/.env first:")
        print("  GMAIL_CLIENT_ID=...")
        print("  GMAIL_CLIENT_SECRET=...")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install dependency first:")
        print("  pip install google-auth-oauthlib")
        return 1

    client_config = {
        "installed": {
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\nAuthorization successful. Add this to Backend/.env:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\nThen set:")
    print("EMAIL_PROVIDER=gmail")
    print("GMAIL_FROM=Iasty <your@gmail.com>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
