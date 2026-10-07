"""FastAPI app. Bind it to 127.0.0.1 and expose it only through `tailscale serve`."""
import asyncio
import hashlib
import contextlib
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .config import Settings, load_settings
from .db import Database
from . import briefing as briefing_mod
from . import morning as morning_mod
from .assistant import Assistant
from .llm import LocalLLM
from .scheduler import daily

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("agent")


class TriageRequest(BaseModel):
    dry_run: bool = True


class ChatRequest(BaseModel):
    text: str


class ApproveRequest(BaseModel):
    mode: str = "send"   # send | draft (emails only)


def create_app(settings: Settings | None = None, gmail=None, db: Database | None = None,
               llm: LocalLLM | None = None, calendar=None, claude=None, slack=None) -> FastAPI:
    settings = settings or load_settings()
    db = db or Database(settings.db_path)
    if not settings.token:
        raise RuntimeError("AGENT_TOKEN is not set; refusing to start without auth.")

    def get_gmail():
        nonlocal gmail
        if gmail is None:  # lazy: the app (and UI) works before Google sign-in is done
            from .auth_google import load_credentials
            from .gmail_client import GoogleGmail
            gmail = GoogleGmail(load_credentials())
        return gmail

    def require_auth(authorization: str = Header(default="")) -> None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token, settings.token):
            raise HTTPException(status_code=401, detail="unauthorized")

    llm = llm or LocalLLM(settings.ollama_url, settings.ollama_model)

    def get_calendar():
        nonlocal calendar
        if calendar is None:
            from .auth_google import CALENDAR_SCOPE, load_credentials
            from .calendar_client import GoogleCalendar
            calendar = GoogleCalendar(load_credentials(require=CALENDAR_SCOPE), settings.timezone)
        return calendar

    def get_claude():
        nonlocal claude
        if claude is None:
            from .secrets import anthropic_key
            key = anthropic_key()
            if not key:
                raise RuntimeError("No Anthropic API key yet. On the Mac mini run: "
                                   "python -m app.secrets set-anthropic-key")
            import anthropic
            claude = anthropic.Anthropic(api_key=key)
        return claude

    def get_slack():
        nonlocal slack
        if slack is None:
            from .secrets import slack_token
            from .slack_client import SlackClient
            token = slack_token()
            if not token:
                return None
            slack = SlackClient(token)
        return slack

    def get_assistant() -> Assistant:
        return Assistant(get_claude(), db, get_gmail, get_calendar, settings)

    morning_state = {"running": False, "error": None}

    async def run_morning():
        if morning_state["running"]:
            return
        morning_state.update(running=True, error=None)
        try:
            gathered = await asyncio.to_thread(morning_mod.gather, get_gmail, get_slack)
            await asyncio.to_thread(morning_mod.build, get_claude(), db, settings.claude_model,
                                    settings.morning_effort, settings.timezone, settings.morning_about,
                                    gathered)
        except Exception as exc:  # shown in the app; never crashes the server
            log.exception("morning briefing failed")
            morning_state["error"] = str(exc)[:300]
        finally:
            morning_state["running"] = False

    chat_lock = asyncio.Lock()
    triage_lock = asyncio.Lock()
    briefing_state = {"running": False, "error": None}

    async def run_briefing():
        if briefing_state["running"]:
            return
        briefing_state.update(running=True, error=None)
        try:
            await asyncio.to_thread(briefing_mod.build_briefing, get_gmail(), db, llm,
                                    1, settings.briefing_max_items)
        except Exception as exc:  # surfaced in the app, never crashes the server
            log.exception("briefing failed")
            briefing_state["error"] = str(exc)[:300]
        finally:
            briefing_state["running"] = False

    async def run_locked(dry_run: bool | None):
        async with triage_lock:  # never two triage runs at once
            return await asyncio.to_thread(service.run_triage, get_gmail(), db, settings, dry_run)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = []
        if settings.triage_at:
            async def nightly():
                await run_locked(None)
            tasks.append(asyncio.create_task(daily(settings.triage_at, nightly)))
        if settings.morning_at:
            tasks.append(asyncio.create_task(daily(settings.morning_at, run_morning)))
        if settings.briefing_enabled and settings.briefing_at:
            tasks.append(asyncio.create_task(daily(settings.briefing_at, run_briefing)))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="Personal Agent", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def no_stale_app(request, call_next):
        # Make the phone re-check the app's files on every load (a cheap 304 when unchanged).
        # Without this, iOS can keep an old app.js after an update and pair it with new HTML.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/status", dependencies=[Depends(require_auth)])
    def status():
        return {"dry_run_default": settings.dry_run, "last_run": db.last_run(),
                "schedule": settings.triage_at or None}

    @app.post("/api/triage/run", dependencies=[Depends(require_auth)])
    async def triage_run(req: TriageRequest):
        try:
            result = await run_locked(req.dry_run)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return result.__dict__

    @app.get("/api/actions", dependencies=[Depends(require_auth)])
    def actions(limit: int = 100, action: str | None = None):
        return db.recent_actions(min(limit, 500), action)

    @app.post("/api/actions/{action_id}/undo", dependencies=[Depends(require_auth)])
    def undo(action_id: int):
        try:
            return service.undo(get_gmail(), db, action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such action")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/briefing", dependencies=[Depends(require_auth)])
    def get_briefing():
        return {"briefing": db.latest_briefing(), **briefing_state}

    @app.post("/api/briefing/run", status_code=202, dependencies=[Depends(require_auth)])
    async def start_briefing():
        if not briefing_state["running"]:
            asyncio.create_task(run_briefing())
        return {"started": True}

    @app.get("/api/morning", dependencies=[Depends(require_auth)])
    def get_morning():
        return {"briefing": db.latest_morning(), **morning_state, "schedule": settings.morning_at or None}

    @app.post("/api/morning/run", status_code=202, dependencies=[Depends(require_auth)])
    async def start_morning():
        if not morning_state["running"]:
            asyncio.create_task(run_morning())
        return {"started": True}

    @app.get("/api/chat", dependencies=[Depends(require_auth)])
    def chat_transcript():
        try:
            return get_assistant().transcript()
        except RuntimeError as exc:
            return {"conversation_id": None, "items": [], "setup": str(exc)}

    @app.post("/api/chat", dependencies=[Depends(require_auth)])
    async def chat_send(req: ChatRequest):
        if len(req.text) > 4000:
            raise HTTPException(status_code=400, detail="message too long")
        async with chat_lock:   # one turn at a time
            try:
                assistant = get_assistant()
                out = await asyncio.to_thread(assistant.send, req.text)
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            except Exception as exc:
                log.exception("chat turn failed")
                raise HTTPException(status_code=502, detail=f"The assistant hit an error: {str(exc)[:200]}")
        return {**out, **assistant.transcript(out["conversation_id"])}

    @app.post("/api/chat/new", dependencies=[Depends(require_auth)])
    def chat_new():
        try:
            return get_assistant().new_chat()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/proposals/{proposal_id}/approve", dependencies=[Depends(require_auth)])
    async def proposal_approve(proposal_id: int, req: ApproveRequest):
        try:
            return await asyncio.to_thread(get_assistant().approve, proposal_id, req.mode)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such proposal")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't complete it: {str(exc)[:200]}")

    @app.post("/api/proposals/{proposal_id}/reject", dependencies=[Depends(require_auth)])
    def proposal_reject(proposal_id: int):
        try:
            return get_assistant().reject(proposal_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such proposal")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/")
    def index():
        # Version the asset URLs by file contents, so a new app.js is never confused with an old one.
        html = (STATIC / "index.html").read_text()
        for name in ("style.css", "app.js"):
            digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:10]
            html = html.replace(f"/static/{name}\"", f"/static/{name}?v={digest}\"")
        return HTMLResponse(html)

    @app.get("/sw.js")
    def sw():  # served from root so its scope covers the whole app
        return FileResponse(STATIC / "sw.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def build() -> FastAPI:  # uvicorn entry point: uvicorn app.main:build --factory
    return create_app()
