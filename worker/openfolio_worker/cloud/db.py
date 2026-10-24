"""SQLite storage for Openfolio Cloud: access requests, invites, the audit log and revoked sessions.

One connection guarded by a lock, used from worker threads (CloudDB.run), so a slow disk never
blocks the event loop. WAL mode lets readers continue during a write. PRAGMA user_version records
the schema version; each stage appends a migration to MIGRATIONS instead of editing an old one.
Stage 2 (the Studio) adds members, their sessions, files, personas and reviews; store.py reads them.
Times are Unix seconds (UTC).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, ParamSpec, TypeVar

from ..config import ConfigError

P = ParamSpec("P")
T = TypeVar("T")

Status = Literal["pending", "approved", "rejected"]
STATUSES: tuple[Status, ...] = ("pending", "approved", "rejected")
DAY = 86_400
INVITE_SECONDS = 7 * DAY
REJECTED_RETENTION = 90 * DAY
EXPIRED_INVITE_RETENTION = 30 * DAY

# Index i upgrades a database from version i to i + 1. Never edit a shipped entry.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE access_requests (
        id INTEGER PRIMARY KEY,
        created_at INTEGER NOT NULL,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        portfolio_url TEXT NOT NULL,
        about TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
        decided_at INTEGER,
        ip_hash TEXT NOT NULL
    );
    CREATE INDEX access_requests_status ON access_requests (status, created_at);
    CREATE INDEX access_requests_email ON access_requests (email, status);
    CREATE TABLE invites (
        id INTEGER PRIMARY KEY,
        request_id INTEGER NOT NULL REFERENCES access_requests (id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at INTEGER
    );
    CREATE INDEX invites_request ON invites (request_id);
    -- No foreign key: the log outlives deleted requests, and holds no personal data.
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        at INTEGER NOT NULL,
        action TEXT NOT NULL,
        request_id INTEGER,
        ip_hash TEXT,
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX audit_log_lookup ON audit_log (ip_hash, action, at);
    CREATE TABLE revoked_sessions (
        sid TEXT PRIMARY KEY,
        expires_at INTEGER NOT NULL
    );
    """,
    # Stage 2: the Studio. Deleting a user cascades to everything they own.
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        handle TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        request_id INTEGER REFERENCES access_requests (id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
        created_at INTEGER NOT NULL,
        last_active_at INTEGER
    );
    CREATE TABLE user_sessions (
        sid_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE INDEX user_sessions_user ON user_sessions (user_id);
    CREATE TABLE password_resets (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at INTEGER
    );
    CREATE INDEX password_resets_user ON password_resets (user_id);
    CREATE TABLE files (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('photo', 'document')),
        stored_name TEXT NOT NULL UNIQUE,
        original_name TEXT NOT NULL,
        mime TEXT NOT NULL,
        size INTEGER NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
    );
    CREATE INDEX files_user ON files (user_id, kind);
    CREATE TABLE personas (
        user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
        handle TEXT NOT NULL UNIQUE,
        data TEXT NOT NULL,
        live_data TEXT,
        status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending', 'live', 'rejected', 'paused')),
        show_in_search INTEGER NOT NULL DEFAULT 1,
        flags TEXT NOT NULL DEFAULT '[]',
        drafted_at INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        published_at INTEGER
    );
    CREATE INDEX personas_status ON personas (status);
    CREATE TABLE reviews (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        data TEXT NOT NULL,
        flags TEXT NOT NULL DEFAULT '[]',
        submitted_at INTEGER NOT NULL,
        decided_at INTEGER,
        decision TEXT CHECK (decision IN ('approved', 'rejected')),
        note TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX reviews_open ON reviews (decided_at, submitted_at);
    CREATE INDEX reviews_user ON reviews (user_id, id);
    ALTER TABLE audit_log ADD COLUMN user_id INTEGER;
    """,
)
SCHEMA_VERSION = len(MIGRATIONS)


@dataclass(frozen=True)
class AccessRequest:
    id: int
    created_at: int
    name: str
    email: str
    portfolio_url: str
    about: str
    reason: str
    status: Status
    decided_at: int | None
    invite_expires_at: int | None = None
    invite_used_at: int | None = None

    def invite_state(self, now: int) -> str | None:
        """The latest invite: None, "used", "expired" or "unused"."""
        if self.invite_expires_at is None:
            return None
        if self.invite_used_at is not None:
            return "used"
        return "expired" if self.invite_expires_at <= now else "unused"


@dataclass(frozen=True)
class AuditEntry:
    at: int
    action: str
    request_id: int | None
    ip_hash: str | None
    detail: str
    user_id: int | None = None


# Interpolated into queries below (S608): constants only; every value is a bound parameter.
_REQUEST_COLUMNS = (
    "r.id, r.created_at, r.name, r.email, r.portfolio_url, r.about, r.reason, r.status, r.decided_at, "
    "(SELECT expires_at FROM invites WHERE request_id = r.id ORDER BY id DESC LIMIT 1), "
    "(SELECT used_at FROM invites WHERE request_id = r.id ORDER BY id DESC LIMIT 1)"
)


class CloudDB:
    def __init__(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit mode: transactions are explicit (see _tx), so each one is easy to read.
            self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
            self._conn.execute("PRAGMA journal_mode = WAL")
        except (OSError, sqlite3.Error) as e:
            raise ConfigError(f"DATA_DIR: cannot open {path} ({e}); mount a writable volume there") from e
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    async def run(self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Call one of the methods below in a worker thread."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One write transaction (BEGIN IMMEDIATE), for store.py; rolled back on any error."""
        with self._tx() as c:
            yield c

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """The connection for reads, held under the lock."""
        with self._lock:
            yield self._conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _migrate(self) -> None:
        with self._tx() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ConfigError(f"DATA_DIR: cloud.db has schema {version}, newer than this server ({SCHEMA_VERSION})")
            for step in range(version, SCHEMA_VERSION):
                for statement in MIGRATIONS[step].split(";"):
                    if statement.strip():
                        c.execute(statement)
                c.execute(f"PRAGMA user_version = {step + 1}")

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    # Access requests

    def add_request(
        self, *, name: str, email: str, portfolio_url: str, about: str, reason: str, ip_hash: str, now: int
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO access_requests (created_at, name, email, portfolio_url, about, reason, ip_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, name, email, portfolio_url, about, reason, ip_hash),
            )
            request_id = int(cur.lastrowid or 0)
            c.execute(
                "INSERT INTO audit_log (at, action, request_id, ip_hash) VALUES (?, 'request.created', ?, ?)",
                (now, request_id, ip_hash),
            )
            return request_id

    def has_pending(self, email: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM access_requests WHERE email = ? AND status = 'pending' LIMIT 1", (email,)
            ).fetchone()
        return row is not None

    def submissions_since(self, ip_hash: str, since: int) -> int:
        """Requests sent from one network, duplicates included, so repeats cannot probe for emails."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE ip_hash = ? AND at > ? "
                "AND action IN ('request.created', 'request.duplicate')",
                (ip_hash, since),
            ).fetchone()
        return int(row[0])

    def get_request(self, request_id: int) -> AccessRequest | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_REQUEST_COLUMNS} FROM access_requests r WHERE r.id = ?",  # noqa: S608
                (request_id,),
            ).fetchone()
        return AccessRequest(*row) if row else None

    def list_requests(self, status: Status, limit: int = 200) -> list[AccessRequest]:
        order = "r.created_at ASC" if status == "pending" else "r.decided_at DESC"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_REQUEST_COLUMNS} FROM access_requests r "  # noqa: S608
                f"WHERE r.status = ? ORDER BY {order}, r.id LIMIT ?",
                (status, limit),
            ).fetchall()
        return [AccessRequest(*row) for row in rows]

    def counts(self) -> dict[Status, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) FROM access_requests GROUP BY status").fetchall()
        found = dict(rows)
        return {status: int(found.get(status, 0)) for status in STATUSES}

    def approve(self, request_id: int, token_hash: str, now: int) -> bool:
        """Approve and issue a fresh invite. Earlier unused invites stop working: one live link per person."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE access_requests SET status = 'approved', decided_at = ? WHERE id = ?", (now, request_id)
            )
            if not cur.rowcount:
                return False
            c.execute("DELETE FROM invites WHERE request_id = ? AND used_at IS NULL", (request_id,))
            c.execute(
                "INSERT INTO invites (request_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (request_id, token_hash, now, now + INVITE_SECONDS),
            )
            return True

    def reject(self, request_id: int, now: int) -> bool:
        with self._tx() as c:
            cur = c.execute(
                "UPDATE access_requests SET status = 'rejected', decided_at = ? WHERE id = ?", (now, request_id)
            )
            c.execute("DELETE FROM invites WHERE request_id = ? AND used_at IS NULL", (request_id,))
            return bool(cur.rowcount)

    def delete_request(self, request_id: int) -> bool:
        """Right to erasure: the request and (through ON DELETE CASCADE) every invite for it."""
        with self._tx() as c:
            return bool(c.execute("DELETE FROM access_requests WHERE id = ?", (request_id,)).rowcount)

    # Invites

    def valid_invite(self, token_hash: str, now: int) -> AccessRequest | None:
        """The approved request behind an unused, unexpired invite; None for anything else."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_REQUEST_COLUMNS} FROM invites i JOIN access_requests r ON r.id = i.request_id "  # noqa: S608
                "WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ? AND r.status = 'approved'",
                (token_hash, now),
            ).fetchone()
        return AccessRequest(*row) if row else None

    # Audit log and admin sessions

    def audit(
        self,
        action: str,
        *,
        now: int,
        request_id: int | None = None,
        ip_hash: str | None = None,
        detail: str = "",
        user_id: int | None = None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO audit_log (at, action, request_id, ip_hash, detail, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                (now, action, request_id, ip_hash, detail[:200], user_id),
            )

    def recent_audit(self, limit: int = 50) -> list[AuditEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT at, action, request_id, ip_hash, detail, user_id FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AuditEntry(*row) for row in rows]

    def failed_logins_since(self, ip_hash: str, since: int, *, prefix: str = "") -> int:
        """Failures from one network in the window, counted from its last successful sign-in.

        prefix "" counts the owner's sign-ins, "user." the members'; the two lockouts are separate.
        """
        failed, success = f"{prefix}login.failed", f"{prefix}login"
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE ip_hash = ? AND action = ? AND at > MAX(?, "
                "COALESCE((SELECT MAX(at) FROM audit_log WHERE ip_hash = ? AND action = ?), 0))",
                (ip_hash, failed, since, ip_hash, success),
            ).fetchone()
        return int(row[0])

    def actions_since(self, action: str, since: int, *, ip_hash: str | None = None, user_id: int | None = None) -> int:
        """How often an action happened in a window, for one network or one member (rate limits)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = ? AND at > ? "
                "AND (? IS NULL OR ip_hash = ?) AND (? IS NULL OR user_id = ?)",
                (action, since, ip_hash, ip_hash, user_id, user_id),
            ).fetchone()
        return int(row[0])

    def last_action(self, user_id: int, actions: tuple[str, ...]) -> tuple[str, int] | None:
        """The most recent of these actions for one member, as (action, at)."""
        marks = ", ".join("?" * len(actions))
        with self._lock:
            row = self._conn.execute(
                f"SELECT action, at FROM audit_log WHERE user_id = ? AND action IN ({marks}) "  # noqa: S608
                "ORDER BY id DESC LIMIT 1",
                (user_id, *actions),
            ).fetchone()
        return (str(row[0]), int(row[1])) if row else None

    def revoke_session(self, sid: str, expires_at: int) -> None:
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO revoked_sessions (sid, expires_at) VALUES (?, ?)", (sid, expires_at))

    def is_revoked(self, sid: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM revoked_sessions WHERE sid = ?", (sid,)).fetchone() is not None

    # Retention

    def purge(self, now: int) -> tuple[int, int]:
        """Delete rejected requests after 90 days and unused invites 30 days after they expire."""
        with self._tx() as c:
            requests = c.execute(
                "DELETE FROM access_requests WHERE status = 'rejected' AND COALESCE(decided_at, created_at) < ?",
                (now - REJECTED_RETENTION,),
            ).rowcount
            invites = c.execute(
                "DELETE FROM invites WHERE used_at IS NULL AND expires_at < ?", (now - EXPIRED_INVITE_RETENTION,)
            ).rowcount
            c.execute("DELETE FROM revoked_sessions WHERE expires_at < ?", (now,))
            c.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now,))
            c.execute("DELETE FROM password_resets WHERE expires_at < ?", (now,))
        return requests, invites
