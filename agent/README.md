# Personal Agent

A private assistant that runs on your Mac mini and is used from an iPhone Home Screen web app.
Data stays on your machine; nothing is exposed to the public internet.

**Status:** inbox triage + web app (steps 1–2 of the build plan). Briefing, calendar, Slack drafts and the
local-model router come next.

## How it's reached (no public domain, no dynamic DNS, no open ports)

The server binds to `127.0.0.1` only. [Tailscale](https://tailscale.com) gives your phone a private,
encrypted path to the Mini and provides the HTTPS certificate iOS needs for Home Screen apps.
An `AGENT_TOKEN` is required on every API call as a second layer.

## What triage does

Runs nightly (and on demand) over **new** inbox mail only:

| Situation | Action |
|---|---|
| Promotion from a domain you've never emailed/starred | **Trash** (reversible; logged; one-tap Restore) |
| Financial/government sender, SSN/card/bank-style content | Never touched |
| Starred, Important, or a thread you replied in | Never touched |
| From someone you've engaged with | Labelled `Agent/Seen`, left in inbox |
| Everything else | Labelled `Agent/Seen`, left in inbox |

Safety properties: starts in **preview mode** (logs only); trash cap per run (default 25); uses Gmail's
`gmail.modify` scope, which **cannot permanently delete**; no language model is involved in these
decisions, so a malicious email can't steer them. Shared providers (gmail.com, icloud.com, …) count as
engaged per exact address, never per domain.

## Setup on the Mac mini

**Requires Python 3.10 or newer.** macOS ships 3.9, which won't work; install 3.12 from python.org first and
create the venv with `python3.12 -m venv .venv`.

```bash
cd Taryns-Repo/agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then set AGENT_TOKEN (see the comment in the file)
```

### 1. Google sign-in (one time)
1. [Google Cloud Console](https://console.cloud.google.com) → new project → enable **Gmail API**.
2. OAuth consent screen → External → add yourself as a **test user**.
3. Credentials → Create → **OAuth client ID → Desktop app** → download as `credentials.json` into `agent/`.
4. `python -m app.auth_google` and approve in the browser. The token goes to the macOS Keychain.
5. Delete `credentials.json`.

(Apps in "testing" status make Google expire the token after 7 days. When that happens, re-run step 4.
Publishing the app as "In production" for personal use avoids this.)

### 2. Run it
```bash
uvicorn app.main:build --factory --host 127.0.0.1 --port 8000
```
To keep it running across reboots, edit the paths in `scripts/com.personal.agent.plist` and load it
with `launchctl` (instructions are in the file).

### 3. Tailscale
1. Install Tailscale on the Mini and on your iPhone; sign in to the same account.
2. On the Mini: `tailscale serve --bg 8000` (prints an `https://<mini>.<tailnet>.ts.net` URL).
3. On the iPhone: open that URL in Safari → Share → **Add to Home Screen**. Enter `AGENT_TOKEN` once.

### 4. First runs
1. Tap **Preview run**. Read the "would trash" list. Tune nothing yet; just check it looks right.
2. When you trust it, set `TRIAGE_DRY_RUN=false` in `.env`, restart, and use **Run for real**.
3. The nightly job runs at `TRIAGE_AT`. Anything it trashed can be restored from the app.

## Develop

```bash
pip install -r requirements-dev.txt
python -m pytest
```
