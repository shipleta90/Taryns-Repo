"""Orchestrates a triage run and undo, using a GmailClient and the Database."""
from dataclasses import dataclass

from .config import Settings
from .db import Database
from .gmail_client import GmailClient
from .triage import Action, EngagedSet, decide

ENGAGED_MAX_AGE_SECONDS = 7 * 24 * 3600


@dataclass
class RunResult:
    run_id: int
    dry_run: bool
    examined: int
    trashed: int
    skipped_by_cap: int


def _engaged(gmail: GmailClient, db: Database) -> EngagedSet:
    """Refresh the engaged-sender cache weekly; Gmail history scans are slow."""
    age = db.engaged_age_seconds()
    if age is None or age > ENGAGED_MAX_AGE_SECONDS:
        fresh = gmail.build_engaged_set()
        db.replace_engaged(fresh.domains, fresh.addresses)
        return fresh
    return EngagedSet(domains=db.engaged_domains(), addresses=db.engaged_addresses())


def run_triage(gmail: GmailClient, db: Database, settings: Settings,
               dry_run: bool | None = None) -> RunResult:
    # An explicit dry_run=True always wins; the API can only make a run SAFER than the config.
    effective_dry = settings.dry_run if dry_run is None else (dry_run or settings.dry_run)
    run_id = db.start_run(effective_dry)
    examined = trashed = capped = 0
    try:
        engaged = _engaged(gmail, db)
        for msg in gmail.list_new_messages(settings.lookback_hours):
            examined += 1
            decision = decide(msg, engaged)
            action = decision.action
            if action is Action.TRASH and trashed >= settings.max_trash_per_run:
                # Circuit breaker: leave the rest for a human to look at.
                action, capped = Action.SKIP, capped + 1
                decision = type(decision)(Action.SKIP, "trash cap reached this run")
            if not effective_dry:
                if action is Action.TRASH:
                    gmail.trash(msg.id)
                elif action is Action.LABEL:
                    gmail.mark_seen(msg.id)
            if action is Action.TRASH:
                trashed += 1
            db.log_action(run_id, msg.id, msg.sender, msg.subject,
                          action.value, decision.reason, effective_dry)
        db.finish_run(run_id, examined, trashed)
    except Exception as exc:  # log the failure on the run, then re-raise for the caller
        db.finish_run(run_id, examined, trashed, error=repr(exc))
        raise
    return RunResult(run_id, effective_dry, examined, trashed, capped)


def undo(gmail: GmailClient, db: Database, action_id: int) -> dict:
    row = db.get_action(action_id)
    if row is None:
        raise KeyError(action_id)
    if row["action"] != Action.TRASH.value or row["dry_run"] or row["undone"]:
        raise ValueError("only real, not-yet-restored trash actions can be undone")
    gmail.untrash(row["message_id"])
    db.mark_undone(action_id)
    return db.get_action(action_id)
