import pytest

from app import service
from app.config import Settings
from app.db import Database
from app.triage import EngagedSet
from tests.fakes import FakeGmail, promo


def settings(tmp_path, dry_run=False, cap=25):
    return Settings(token="t", dry_run=dry_run, max_trash_per_run=cap, lookback_hours=24,
                    triage_at="", data_dir=tmp_path)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.sqlite3")


def test_dry_run_changes_nothing(db, tmp_path):
    g = FakeGmail([promo(1), promo(2)])
    r = service.run_triage(g, db, settings(tmp_path, dry_run=True))
    assert r.dry_run and r.trashed == 2
    assert g.trashed == [] and g.seen == []
    assert all(a["dry_run"] for a in db.recent_actions())


def test_request_cannot_disable_config_dry_run(db, tmp_path):
    g = FakeGmail([promo(1)])
    r = service.run_triage(g, db, settings(tmp_path, dry_run=True), dry_run=False)
    assert r.dry_run and g.trashed == []


def test_live_run_trashes_and_logs(db, tmp_path):
    g = FakeGmail([promo(1), promo(2, sender="Pat <pat@friend.com>")], engaged=EngagedSet(domains={"friend.com"}))
    r = service.run_triage(g, db, settings(tmp_path))
    assert g.trashed == ["m1"] and g.seen == ["m2"]
    assert r.examined == 2 and r.trashed == 1
    assert db.last_run()["trashed"] == 1


def test_trash_cap_is_a_circuit_breaker(db, tmp_path):
    g = FakeGmail([promo(i) for i in range(10)])
    r = service.run_triage(g, db, settings(tmp_path, cap=3))
    assert len(g.trashed) == 3 and r.skipped_by_cap == 7


def test_engaged_cache_reused(db, tmp_path):
    g = FakeGmail([promo(1)])
    service.run_triage(g, db, settings(tmp_path))
    service.run_triage(g, db, settings(tmp_path))
    assert g.engaged_builds == 1


def test_failure_is_recorded(db, tmp_path):
    g = FakeGmail([promo(1)])
    g.trash = lambda _id: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        service.run_triage(g, db, settings(tmp_path))
    assert "boom" in db.last_run()["error"]


def test_undo(db, tmp_path):
    g = FakeGmail([promo(1)])
    service.run_triage(g, db, settings(tmp_path))
    aid = db.recent_actions()[0]["id"]
    service.undo(g, db, aid)
    assert g.restored == ["m1"] and db.get_action(aid)["undone"] == 1
    with pytest.raises(ValueError):
        service.undo(g, db, aid)  # already restored


def test_cannot_undo_dry_run(db, tmp_path):
    g = FakeGmail([promo(1)])
    service.run_triage(g, db, settings(tmp_path, dry_run=True))
    with pytest.raises(ValueError):
        service.undo(g, db, db.recent_actions()[0]["id"])


def test_cached_engaged_addresses_survive(db, tmp_path):
    g = FakeGmail([promo(1, sender="pat@gmail.com")], engaged=EngagedSet(addresses={"pat@gmail.com"}))
    service.run_triage(g, db, settings(tmp_path))
    g.messages = [promo(2, sender="pat@gmail.com")]
    service.run_triage(g, db, settings(tmp_path))  # served from cache
    assert g.engaged_builds == 1 and g.trashed == []
