import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from openfolio_worker.cloud.auth import Keys
from openfolio_worker.cloud.db import DAY, INVITE_SECONDS, CloudDB
from openfolio_worker.config import ConfigError
from openfolio_worker.server import create_app

NOW = 1_800_000_000


def add(db: CloudDB, email: str = "a@example.com", now: int = NOW) -> int:
    return db.add_request(
        name="A", email=email, portfolio_url="https://a.dev", about="Dev", reason="", ip_hash="h", now=now
    )


def test_schema_version_wal_and_reopen(tmp_path):
    db = CloudDB(tmp_path / "cloud.db")
    assert db.schema_version == 2
    add(db)
    db.close()
    conn = sqlite3.connect(tmp_path / "cloud.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    again = CloudDB(tmp_path / "cloud.db")  # migrating twice must not fail or lose rows
    assert again.counts()["pending"] == 1


def test_newer_schema_is_refused(tmp_path):
    conn = sqlite3.connect(tmp_path / "cloud.db")
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(ConfigError, match="DATA_DIR"):
        CloudDB(tmp_path / "cloud.db")


def test_unwritable_data_dir_is_a_config_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(ConfigError, match="DATA_DIR"):
        CloudDB(blocker / "cloud.db")


def test_purge_retention(tmp_path):
    db = CloudDB(tmp_path / "cloud.db")
    old_rejected = add(db, "old@example.com", NOW - 100 * DAY)
    db.reject(old_rejected, NOW - 91 * DAY)
    recent_rejected = add(db, "recent@example.com")
    db.reject(recent_rejected, NOW - 10 * DAY)
    old_pending = add(db, "pending@example.com", NOW - 200 * DAY)

    stale = add(db, "stale@example.com", NOW - 60 * DAY)
    db.approve(stale, "stale-hash", NOW - 60 * DAY)  # expired 53 days ago, never used
    fresh = add(db, "fresh@example.com", NOW - 20 * DAY)
    db.approve(fresh, "fresh-hash", NOW - 20 * DAY)  # expired 13 days ago
    used = add(db, "used@example.com", NOW - 60 * DAY)
    db.approve(used, "used-hash", NOW - 60 * DAY)
    with db._tx() as c:
        c.execute("UPDATE invites SET used_at = ? WHERE token_hash = 'used-hash'", (NOW - 59 * DAY,))

    assert db.purge(NOW) == (1, 1)
    assert db.get_request(old_rejected) is None
    assert db.get_request(recent_rejected) is not None
    assert db.get_request(old_pending) is not None
    assert db.get_request(stale).invite_expires_at is None
    assert db.get_request(fresh).invite_expires_at == NOW - 20 * DAY + INVITE_SECONDS
    assert db.get_request(used).invite_used_at is not None


def test_purge_runs_on_startup(cloud_settings):
    db = CloudDB(cloud_settings.data_dir / "cloud.db")
    old = add(db, now=int(time.time()) - 200 * DAY)
    db.reject(old, int(time.time()) - 120 * DAY)
    db.close()
    with TestClient(create_app(cloud_settings)) as client:
        state_db = client.app.state.cloud.db
        assert state_db.get_request(old) is None
        assert any(e.action == "purge" for e in state_db.recent_audit())


def test_ip_hash_is_salted_and_never_the_address():
    one, two = Keys("a" * 40), Keys("b" * 40)
    assert one.ip_hash("203.0.113.9") == one.ip_hash("203.0.113.9")
    assert one.ip_hash("203.0.113.9") != two.ip_hash("203.0.113.9")
    assert "203.0.113.9" not in one.ip_hash("203.0.113.9")
