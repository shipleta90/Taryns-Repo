import json

import pytest

from app import auth_google


def test_client_config_rebuilt_from_saved_token():
    raw = json.dumps({"client_id": "abc.apps.googleusercontent.com", "client_secret": "s3cret",
                      "refresh_token": "r", "token_uri": "https://oauth2.googleapis.com/token"})
    cfg = auth_google.client_config_from_saved_token(raw)["installed"]
    assert cfg["client_id"] == "abc.apps.googleusercontent.com" and cfg["client_secret"] == "s3cret"
    assert auth_google.client_config_from_saved_token(None) is None
    assert auth_google.client_config_from_saved_token(json.dumps({"refresh_token": "r"})) is None


def test_expired_sign_in_gives_clear_instructions(monkeypatch):
    from google.auth.exceptions import RefreshError

    saved = {"client_id": "a", "client_secret": "b", "refresh_token": "r", "token": "t",
             "token_uri": "https://oauth2.googleapis.com/token", "scopes": [auth_google.GMAIL_SCOPE],
             "expiry": "2020-01-01T00:00:00Z"}
    monkeypatch.setattr(auth_google.keyring, "get_password", lambda s, a: json.dumps(saved))

    def refuse(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(auth_google.Credentials, "refresh", refuse)
    with pytest.raises(RuntimeError, match="python -m app.auth_google"):
        auth_google.load_credentials()
