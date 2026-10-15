"""Google sign-in. Run on the Mac mini:  python -m app.auth_google

First time: needs credentials.json (an OAuth "Desktop app" client from Google Cloud Console) in the
working directory. After that, signing in again (e.g. when Google expires the sign-in) needs no
download: the app's client details are reused from the saved sign-in in the macOS Keychain.
"""
import json
import os

import keyring
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .gmail_client import SCOPES

SERVICE = "personal-agent"
ACCOUNT = "google-oauth-token"


GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def load_credentials(require: str = GMAIL_SCOPE) -> Credentials:
    raw = keyring.get_password(SERVICE, ACCOUNT)
    if not raw:
        raise RuntimeError("Not signed in to Google. Run: python -m app.auth_google")
    info = json.loads(raw)
    if require not in (info.get("scopes") or []):
        # Older sign-ins predate Calendar access; triage keeps working, chat asks for a re-sign-in.
        raise RuntimeError(
            "Google sign-in is missing a permission this needs. Run on the Mac mini: "
            "python -m app.auth_google"
        )
    creds = Credentials.from_authorized_user_info(info)  # use exactly the scopes that were granted
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # In Google's "Testing" mode sign-ins expire after 7 days; this is that case.
            raise RuntimeError(EXPIRED) from exc
        keyring.set_password(SERVICE, ACCOUNT, creds.to_json())
    return creds


EXPIRED = "Google sign-in expired. On the Mac mini run: python -m app.auth_google (then restart the agent)."


def client_config_from_saved_token(raw: str | None) -> dict | None:
    """Rebuild the OAuth client details from a saved sign-in, so re-signing needs no new download."""
    if not raw:
        return None
    info = json.loads(raw)
    if not info.get("client_id") or not info.get("client_secret"):
        return None
    return {"installed": {
        "client_id": info["client_id"], "client_secret": info["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": info.get("token_uri") or "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}


def main() -> None:
    if os.path.exists("credentials.json"):
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    else:
        config = client_config_from_saved_token(keyring.get_password(SERVICE, ACCOUNT))
        if config is None:
            raise SystemExit("First sign-in needs credentials.json in this folder (see the README).")
        flow = InstalledAppFlow.from_client_config(config, SCOPES)
    creds = flow.run_local_server(port=0)
    keyring.set_password(SERVICE, ACCOUNT, creds.to_json())
    print("Signed in. Token saved to the macOS Keychain. Restart the agent to use it."
          + (" You can delete credentials.json now." if os.path.exists("credentials.json") else ""))


if __name__ == "__main__":
    main()
