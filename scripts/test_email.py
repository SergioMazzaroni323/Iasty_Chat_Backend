"""Send a test email using settings from Backend/.env.

Usage:
  cd Backend
  python scripts/test_email.py you@example.com
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.email import email_configured, get_email_provider, get_last_email_error, send_email


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_email.py recipient@example.com")
        return 1

    if not email_configured():
        print("Email is not configured.")
        print("Gmail API (send from your @gmail.com):")
        print("  EMAIL_PROVIDER=gmail")
        print("  GMAIL_CLIENT_ID=...")
        print("  GMAIL_CLIENT_SECRET=...")
        print("  GMAIL_REFRESH_TOKEN=...")
        print("  GMAIL_FROM=Iasty <your@gmail.com>")
        print("Run once: python scripts/gmail_authorize.py")
        return 1

    recipient = sys.argv[1]
    provider = get_email_provider()
    print(f"Sending test email via {provider} to {recipient} ...")
    ok = send_email(
        recipient,
        "Iasty test email",
        "<p>If you received this, email delivery is working.</p>",
        "If you received this, email delivery is working.",
    )
    if ok:
        print("Sent successfully. Check inbox and spam.")
        return 0

    print(f"Send failed: {get_last_email_error() or 'unknown error'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
