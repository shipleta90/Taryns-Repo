"""FastAPI app. Bind it to 127.0.0.1 and expose it only through `tailscale serve`."""
import asyncio
import contextlib
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .config import Settings, load_settings
from .db import Database
from .scheduler import daily

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("agent")


class TriageRequest(BaseModel):
    dry_run: bool = True


def create_app(settings: Settings | None = None, gmail=None, db: Database | None = None) -> FastAPI:
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

    triage_lock = asyncio.Lock()

    async def run_locked(dry_run: bool | None):
        async with triage_lock:  # never two triage runs at once
            return await asyncio.to_thread(service.run_triage, get_gmail(), db, settings, dry_run)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = None
        if settings.triage_at:
            async def nightly():
                await run_locked(None)
            task = asyncio.create_task(daily(settings.triage_at, nightly))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Personal Agent", lifespan=lifespan, docs_url=None, redoc_url=None)

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

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/sw.js")
    def sw():  # served from root so its scope covers the whole app
        return FileResponse(STATIC / "sw.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def build() -> FastAPI:  # uvicorn entry point: uvicorn app.main:build --factory
    return create_app()
