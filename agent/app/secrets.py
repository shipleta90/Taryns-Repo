"""Secrets kept in the macOS Keychain, not in files.

    python -m app.secrets set-anthropic-key     # paste your key when asked (input is hidden)
    python -m app.secrets set-slack-token       # your Slack app's User OAuth Token (xoxp-...)
    python -m app.secrets set-simplefin         # a SimpleFIN Setup Token (read-only bank feed)
"""
import getpass
import os
import sys

SERVICE = "personal-agent"
ANTHROPIC = "anthropic-api-key"
SLACK = "slack-user-token"
SIMPLEFIN = "simplefin-access-url"

# command -> (keychain account, prompt, required prefix)
COMMANDS = {
    "set-anthropic-key": (ANTHROPIC, "Paste your Anthropic API key (hidden): ", "sk-ant-"),
    "set-slack-token": (SLACK, "Paste your Slack User OAuth Token (hidden): ", "xoxp-"),
}


def _get(account: str, env: str) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    try:
        import keyring
        return keyring.get_password(SERVICE, account)
    except Exception:  # no keyring backend (e.g. tests, Linux CI)
        return None


def anthropic_key() -> str | None:
    return _get(ANTHROPIC, "ANTHROPIC_API_KEY")


def slack_token() -> str | None:
    return _get(SLACK, "SLACK_USER_TOKEN")


def simplefin_access_url() -> str | None:
    return _get(SIMPLEFIN, "SIMPLEFIN_ACCESS_URL")


def _set_simplefin() -> None:
    import keyring

    from .simplefin import SimpleFINError, claim
    token = getpass.getpass("Paste your SimpleFIN Setup Token (hidden): ").strip()
    try:
        access_url = claim(token)
    except SimpleFINError as exc:
        raise SystemExit(str(exc))
    keyring.set_password(SERVICE, SIMPLEFIN, access_url)
    print("Connected. The bank feed's access is saved in the macOS Keychain. Restart the agent to use it.")


def main() -> None:
    if sys.argv[1:] == ["set-simplefin"]:
        return _set_simplefin()
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("usage: python -m app.secrets " + " | ".join([*COMMANDS, "set-simplefin"]))
    import keyring
    account, prompt, prefix = COMMANDS[sys.argv[1]]
    value = getpass.getpass(prompt).strip()
    if not value.startswith(prefix):
        raise SystemExit(f"That doesn't look right (it should start with {prefix}).")
    keyring.set_password(SERVICE, account, value)
    print("Saved to the macOS Keychain. Restart the agent to use it.")


if __name__ == "__main__":
    main()
