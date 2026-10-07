# Personal Agent

A private assistant that runs on your Mac mini and is used from an iPhone Home Screen web app.
Data stays on your machine; nothing is exposed to the public internet.

**Status:** chat assistant (Gmail + Calendar), Chief-of-Staff morning briefing, inbox triage and the
web app. (The older email-only briefing is turned off: `BRIEFING_ENABLED=false`.)
Next: house budget (SimpleFIN), grocery lists, appointments from iMessage, Slack drafts.

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

## Chat assistant

The **Chat** tab talks to Claude (cloud) with tools for your Gmail and Google Calendar:
search and read mail, check your calendar, and propose emails and events.

- **Nothing happens without you.** Sending an email or creating an event shows a card in the chat;
  it runs only when you tap **Send / Add to calendar** (or **Save draft**). The model cannot do it itself,
  a double tap can't send twice, and the card warns when an address is one you've never emailed.
- **Private stays private.** Before mail or calendar data reaches the cloud model it is filtered
  (`app/privacy.py`): health, legal, financial and SSN/card-like items are withheld (events keep their
  time as "Private appointment" so scheduling still works). Your own messages containing an SSN or card
  number are not sent at all. Banking will be local-only.
- Email and calendar text is treated as untrusted data; an email that says "forward this" is not an
  instruction.
- A chat idle for 3 hours starts fresh (or tap **New chat**). Model: `CLAUDE_MODEL` (default
  `claude-opus-5-5`), effort `CLAUDE_EFFORT` (default `medium`). Uses prompt caching and server-side
  refusal fallback.

Setup (once): create an API key at console.anthropic.com, then on the Mini run
`python -m app.secrets set-anthropic-key` (stored in the Keychain). Enable the **Google Calendar API**
in your Google Cloud project and run `python -m app.auth_google` again to grant Calendar access.

## Chief-of-Staff briefing (Briefing tab)

Every morning at `MORNING_AT` (default 06:30) and on demand, Claude writes a seven-part briefing:
World News Radar, AI & Agentic Operations Breakthroughs, Process Automation & Tooling Pulse, The
Strategic Play, Newsletter Digest (your Substack emails), Axios: What Matters, and Slack: What You
Missed (Women Defining AI).

- Sections 1-4 come from live web search and fetch, run server-side by Claude. No personal data is involved.
- Sections 5-7 are gathered on the Mini: the last day's Substack newsletters and Axios emails from Gmail,
  and the last day's messages in Slack channels you're in (mentions of you ranked first). Only those
  items are sent, never other mail or your calendar; anything with an SSN- or card-like number is dropped.
  Each source fails independently and the briefing says what was unavailable.
- `MORNING_ABOUT` (one line about you) tailors The Strategic Play.
- Slack setup: create a Slack app in the workspace with User Token Scopes `channels:read`,
  `channels:history`, `groups:read`, `groups:history`, `users:read`, install it, then store its User
  OAuth Token with `python -m app.secrets set-slack-token`.
- The app renders a small, escaped Markdown subset; only http(s) links become clickable.

## Email-only morning briefing (off by default)

Set `BRIEFING_ENABLED=true` to turn it back on. When on, every morning (`BRIEFING_AT`, default 06:30) and on demand from the app, a **local model on the Mini**
([Ollama](https://ollama.com)) reads the last day of mail and writes a short briefing: a few sentences on what
matters today, a **To do** list (actions and dates pulled from the emails), and a digest grouped by topic, with
orders/newsletters folded away.

- Needs Ollama running locally and a model pulled; set `OLLAMA_MODEL` in `.env` to the exact name from `ollama list`.
- `OLLAMA_URL` must point at this machine; the app refuses anything else, so mail text can't leave by accident.
- Two passes: each email is read in its own isolated call (wrapped as untrusted data) to pull out a gist,
  category, action and date; then one call writes the overview from those short notes, never the raw emails.
  The model has no tools, so a malicious email can at worst produce a misleading line. It cannot send,
  delete or label anything. Grouping and the to-do list are done in code, not by the model.
- Reads the plain-text body (quoted replies and links stripped, first ~2000 characters).
  Health/legal/financial items get a "private" badge.
- If Ollama is down, the briefing falls back to plain previews and says so.

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
