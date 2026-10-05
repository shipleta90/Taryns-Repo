"""One-time Google sign-in. Run on the Mac mini:  python -m app.auth_google

Needs credentials.json (an OAuth "Desktop app" client from Google Cloud Console) in the
working directory. The resulting token is stored in the macOS Keychain, not on disk.
"""
import json

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .gmail_client import SCOPES

SERVICE = "personal-agent"
ACCOUNT = "google-oauth-token"


def load_credentials() -> Credentials:
    raw = keyring.get_password(SERVICE, ACCOUNT)
    if not raw:
        raise RuntimeError("Not signed in to Google. Run: python -m app.auth_google")
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        keyring.set_password(SERVICE, ACCOUNT, creds.to_json())
    return creds


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    keyring.set_password(SERVICE, ACCOUNT, creds.to_json())
    print("Signed in. Token saved to the macOS Keychain. You can delete credentials.json now.")


if __name__ == "__main__":
    main()
