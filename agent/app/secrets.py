"""Secrets kept in the macOS Keychain, not in files.

    python -m app.secrets set-anthropic-key     # paste your key when asked (input is hidden)
"""
import getpass
import os
import sys

SERVICE = "personal-agent"
ANTHROPIC = "anthropic-api-key"


def anthropic_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        import keyring
        return keyring.get_password(SERVICE, ANTHROPIC)
    except Exception:  # no keyring backend (e.g. tests, Linux CI)
        return None


def main() -> None:
    if sys.argv[1:] != ["set-anthropic-key"]:
        raise SystemExit("usage: python -m app.secrets set-anthropic-key")
    import keyring
    key = getpass.getpass("Paste your Anthropic API key (hidden): ").strip()
    if not key.startswith("sk-ant-"):
        raise SystemExit("That doesn't look like an Anthropic API key (should start with sk-ant-).")
    keyring.set_password(SERVICE, ANTHROPIC, key)
    print("Saved to the macOS Keychain. Restart the agent to use it.")


if __name__ == "__main__":
    main()
