"""Members, their sessions and password resets, files, personas and go-live reviews.

The tables come from migration 2 in db.py; this module only reads and writes them. Every query
that touches a member's data takes the member's id, so one member can never reach another's rows.
Methods are synchronous: call them through CloudDB.run so the event loop never waits on the disk.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

from .db import CloudDB

UserStatus = Literal["active", "paused"]
PersonaStatus = Literal["draft", "pending", "live", "rejected", "paused"]
FileKind = Literal["photo", "document"]
Decision = Literal["approved", "rejected"]
LAST_ACTIVE_RESOLUTION = 300  # write "last active" at most every five minutes per member


@dataclass(frozen=True)
class User:
    id: int
    handle: str
    email: str
    name: str
    password_hash: str = field(repr=False)
    request_id: int | None
    status: UserStatus
    created_at: int
    last_active_at: int | None


@dataclass(frozen=True)
class StoredFile:
    id: int
    user_id: int
    kind: FileKind
    stored_name: str
    original_name: str
    mime: str
    size: int
    text: str = field(repr=False)
    created_at: int


@dataclass(frozen=True)
class PersonaRecord:
    user_id: int
    handle: str
    data: dict[str, Any]
    live_data: dict[str, Any] | None
    status: PersonaStatus
    show_in_search: bool
    flags: list[dict[str, str]]
    drafted_at: int | None
    created_at: int
    updated_at: int
    published_at: int | None

    @property
    def has_unpublished_changes(self) -> bool:
        return self.live_data is not None and self.data != self.live_data


@dataclass(frozen=True)
class Review:
    id: int
    user_id: int
    handle: str
    email: str
    data: dict[str, Any]
    flags: list[dict[str, str]]
    submitted_at: int
    decided_at: int | None
    decision: Decision | None
    note: str
    live_before: bool  # an update to a profile that is already live


@dataclass(frozen=True)
class Member:
    id: int
    handle: str
    email: str
    name: str
    status: UserStatus
    created_at: int
    last_active_at: int | None
    persona_status: PersonaStatus | None


@dataclass(frozen=True)
class ListedProfile:
    handle: str
    updated_at: int


_USER_COLUMNS = (
    "u.id, u.handle, u.email, u.name, u.password_hash, u.request_id, u.status, u.created_at, u.last_active_at"
)
_FILE_COLUMNS = "id, user_id, kind, stored_name, original_name, mime, size, text, created_at"
_PERSONA_COLUMNS = (
    "user_id, handle, data, live_data, status, show_in_search, flags, drafted_at, created_at, updated_at, published_at"
)


def _user(row: tuple[Any, ...] | None) -> User | None:
    return User(*row) if row else None


def _persona(row: tuple[Any, ...] | None) -> PersonaRecord | None:
    if not row:
        return None
    user_id, handle, data, live, status, search, flags, drafted, created, updated, published = row
    return PersonaRecord(
        user_id=user_id,
        handle=handle,
        data=json.loads(data),
        live_data=json.loads(live) if live else None,
        status=status,
        show_in_search=bool(search),
        flags=json.loads(flags),
        drafted_at=drafted,
        created_at=created,
        updated_at=updated,
        published_at=published,
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class SignupError(Exception):
    """Why an account could not be created: "invite", "handle" or "email"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StudioStore:
    def __init__(self, db: CloudDB) -> None:
        self.db = db

    # Members

    def create_user(
        self,
        *,
        token_hash: str,
        handle: str,
        password_hash: str,
        persona_data: dict[str, Any],
        now: int,
    ) -> User:
        """Create the member, their empty persona and use up the invite, all in one transaction."""
        with self.db.transaction() as c:
            invite = c.execute(
                "SELECT i.id, r.id, r.email, r.name FROM invites i JOIN access_requests r ON r.id = i.request_id "
                "WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ? AND r.status = 'approved'",
                (token_hash, now),
            ).fetchone()
            if invite is None:
                raise SignupError("invite")
            invite_id, request_id, email, name = invite
            if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise SignupError("email")
            if c.execute("SELECT 1 FROM users WHERE handle = ?", (handle,)).fetchone():
                raise SignupError("handle")
            cur = c.execute(
                "INSERT INTO users (handle, email, name, password_hash, request_id, created_at, last_active_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (handle, email, name, password_hash, request_id, now, now),
            )
            user_id = int(cur.lastrowid or 0)
            c.execute("UPDATE invites SET used_at = ? WHERE id = ?", (now, invite_id))
            c.execute(
                "INSERT INTO personas (user_id, handle, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, handle, _dump(persona_data), now, now),
            )
            row = c.execute(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.id = ?", (user_id,)).fetchone()  # noqa: S608
        user = _user(row)
        assert user is not None  # noqa: S101 - inserted above
        return user

    def handle_taken(self, handle: str) -> bool:
        with self.db.reading() as c:
            return c.execute("SELECT 1 FROM users WHERE handle = ?", (handle,)).fetchone() is not None

    def get_user(self, user_id: int) -> User | None:
        with self.db.reading() as c:
            return _user(c.execute(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.id = ?", (user_id,)).fetchone())  # noqa: S608

    def user_by_email(self, email: str) -> User | None:
        with self.db.reading() as c:
            return _user(c.execute(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.email = ?", (email,)).fetchone())  # noqa: S608

    def set_password(self, user_id: int, password_hash: str, *, keep_session: str | None = None) -> None:
        """Change the password and sign out every other session (keep_session is the current one's hash)."""
        with self.db.transaction() as c:
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            c.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND sid_hash IS NOT ?", (user_id, keep_session or "")
            )
            c.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))

    def set_user_status(self, user_id: int, status: UserStatus) -> bool:
        with self.db.transaction() as c:
            changed = c.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id)).rowcount
            if status == "paused":
                c.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            return bool(changed)

    def touch(self, user_id: int, now: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE users SET last_active_at = ? WHERE id = ? AND COALESCE(last_active_at, 0) < ?",
                (now, user_id, now - LAST_ACTIVE_RESOLUTION),
            )

    def delete_user(self, user_id: int) -> User | None:
        """Erase the member: sessions, resets, files, persona and reviews cascade; the original request goes too."""
        with self.db.transaction() as c:
            user = _user(c.execute(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.id = ?", (user_id,)).fetchone())  # noqa: S608
            if user is None:
                return None
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if user.request_id is not None:
                c.execute("DELETE FROM access_requests WHERE id = ?", (user.request_id,))
            # The audit log keeps events but no longer points at the person.
            c.execute("UPDATE audit_log SET user_id = NULL, request_id = NULL WHERE user_id = ?", (user_id,))
            return user

    def list_members(self, limit: int = 500) -> list[Member]:
        with self.db.reading() as c:
            rows = c.execute(
                "SELECT u.id, u.handle, u.email, u.name, u.status, u.created_at, u.last_active_at, p.status "
                "FROM users u LEFT JOIN personas p ON p.user_id = u.id ORDER BY u.created_at DESC, u.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Member(*row) for row in rows]

    def member_count(self) -> int:
        with self.db.reading() as c:
            return int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    # Sessions (only a hash of the session id is stored, so a database copy cannot sign anyone in)

    def add_session(self, sid_hash: str, user_id: int, now: int, expires_at: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO user_sessions (sid_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (sid_hash, user_id, now, expires_at),
            )

    def session_user(self, sid_hash: str, now: int) -> User | None:
        with self.db.reading() as c:
            row = c.execute(
                f"SELECT {_USER_COLUMNS} FROM user_sessions s JOIN users u ON u.id = s.user_id "  # noqa: S608
                "WHERE s.sid_hash = ? AND s.expires_at > ? AND u.status = 'active'",
                (sid_hash, now),
            ).fetchone()
        return _user(row)

    def delete_session(self, sid_hash: str) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM user_sessions WHERE sid_hash = ?", (sid_hash,))

    def session_count(self, user_id: int, now: int) -> int:
        with self.db.reading() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM user_sessions WHERE user_id = ? AND expires_at > ?", (user_id, now)
            ).fetchone()
        return int(row[0])

    # Password resets (single use, one live link per member)

    def add_reset(self, token_hash: str, user_id: int, now: int, expires_at: int) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
            c.execute(
                "INSERT INTO password_resets (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, now, expires_at),
            )

    def valid_reset(self, token_hash: str, now: int) -> User | None:
        with self.db.reading() as c:
            row = c.execute(
                f"SELECT {_USER_COLUMNS} FROM password_resets r JOIN users u ON u.id = r.user_id "  # noqa: S608
                "WHERE r.token_hash = ? AND r.used_at IS NULL AND r.expires_at > ?",
                (token_hash, now),
            ).fetchone()
        return _user(row)

    def use_reset(self, token_hash: str, password_hash: str, now: int) -> User | None:
        """Set the new password and sign out everywhere; None when the link is used, expired or unknown."""
        with self.db.transaction() as c:
            row = c.execute(
                f"SELECT {_USER_COLUMNS} FROM password_resets r JOIN users u ON u.id = r.user_id "  # noqa: S608
                "WHERE r.token_hash = ? AND r.used_at IS NULL AND r.expires_at > ?",
                (token_hash, now),
            ).fetchone()
            user = _user(row)
            if user is None:
                return None
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user.id))
            c.execute("DELETE FROM password_resets WHERE user_id = ?", (user.id,))
            c.execute("DELETE FROM user_sessions WHERE user_id = ?", (user.id,))
            return user

    # Files

    def add_file(
        self,
        *,
        user_id: int,
        kind: FileKind,
        stored_name: str,
        original_name: str,
        mime: str,
        size: int,
        text: str,
        now: int,
    ) -> int:
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO files (user_id, kind, stored_name, original_name, mime, size, text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, kind, stored_name, original_name, mime, size, text, now),
            )
            return int(cur.lastrowid or 0)

    def list_files(self, user_id: int, kind: FileKind | None = None) -> list[StoredFile]:
        with self.db.reading() as c:
            rows = c.execute(
                f"SELECT {_FILE_COLUMNS} FROM files WHERE user_id = ? AND (? IS NULL OR kind = ?) "  # noqa: S608
                "ORDER BY id",
                (user_id, kind, kind),
            ).fetchall()
        return [StoredFile(*row) for row in rows]

    def get_file(self, user_id: int, file_id: int) -> StoredFile | None:
        with self.db.reading() as c:
            row = c.execute(
                f"SELECT {_FILE_COLUMNS} FROM files WHERE id = ? AND user_id = ?",  # noqa: S608
                (file_id, user_id),
            ).fetchone()
        return StoredFile(*row) if row else None

    def delete_file(self, user_id: int, file_id: int) -> StoredFile | None:
        with self.db.transaction() as c:
            row = c.execute(
                f"SELECT {_FILE_COLUMNS} FROM files WHERE id = ? AND user_id = ?",  # noqa: S608
                (file_id, user_id),
            ).fetchone()
            if row:
                c.execute("DELETE FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
        return StoredFile(*row) if row else None

    def usage(self, user_id: int) -> tuple[int, int]:
        """(number of files, total bytes) stored for a member."""
        with self.db.reading() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row[0]), int(row[1])

    # Personas

    def get_persona(self, user_id: int) -> PersonaRecord | None:
        with self.db.reading() as c:
            row = c.execute(f"SELECT {_PERSONA_COLUMNS} FROM personas WHERE user_id = ?", (user_id,)).fetchone()  # noqa: S608
        return _persona(row)

    def visible_persona(self, handle: str) -> PersonaRecord | None:
        """A persona the public may see: live, and its member not paused by the owner."""
        with self.db.reading() as c:
            row = c.execute(
                f"SELECT {', '.join('p.' + col.strip() for col in _PERSONA_COLUMNS.split(','))} "  # noqa: S608
                "FROM personas p JOIN users u ON u.id = p.user_id "
                "WHERE p.handle = ? AND p.status = 'live' AND p.live_data IS NOT NULL AND u.status = 'active'",
                (handle,),
            ).fetchone()
        return _persona(row)

    def persona_by_handle(self, handle: str) -> PersonaRecord | None:
        with self.db.reading() as c:
            row = c.execute(f"SELECT {_PERSONA_COLUMNS} FROM personas WHERE handle = ?", (handle,)).fetchone()  # noqa: S608
        return _persona(row)

    def save_persona(
        self, user_id: int, data: dict[str, Any], flags: list[dict[str, str]], now: int, *, drafted: bool = False
    ) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE personas SET data = ?, flags = ?, updated_at = ?, "
                "drafted_at = CASE WHEN ? THEN ? ELSE drafted_at END WHERE user_id = ?",
                (_dump(data), _dump(flags), now, drafted, now, user_id),
            )

    def set_show_in_search(self, user_id: int, show: bool, now: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE personas SET show_in_search = ?, updated_at = ? WHERE user_id = ?", (int(show), now, user_id)
            )

    def set_paused(self, user_id: int, paused: bool, now: int) -> bool:
        """The member pauses or resumes their own live profile; resuming needs an approved version."""
        old, new = ("live", "paused") if paused else ("paused", "live")
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE personas SET status = ?, updated_at = ? WHERE user_id = ? AND status = ? "
                "AND live_data IS NOT NULL",
                (new, now, user_id, old),
            )
            return bool(cur.rowcount)

    def live_personas(self) -> list[tuple[str, dict[str, Any]]]:
        """(handle, approved persona) for every profile the public may call."""
        with self.db.reading() as c:
            rows = c.execute(
                "SELECT p.handle, p.live_data FROM personas p JOIN users u ON u.id = p.user_id "
                "WHERE p.status = 'live' AND p.live_data IS NOT NULL AND u.status = 'active' ORDER BY p.handle"
            ).fetchall()
        return [(handle, json.loads(data)) for handle, data in rows]

    def listed_profiles(self) -> list[ListedProfile]:
        """Live profiles whose members want to appear in search engines (for the sitemap)."""
        with self.db.reading() as c:
            rows = c.execute(
                "SELECT p.handle, COALESCE(p.published_at, p.updated_at) FROM personas p "
                "JOIN users u ON u.id = p.user_id WHERE p.status = 'live' AND p.live_data IS NOT NULL "
                "AND p.show_in_search = 1 AND u.status = 'active' ORDER BY p.handle"
            ).fetchall()
        return [ListedProfile(handle, int(updated)) for handle, updated in rows]

    # Reviews

    def submit(self, user_id: int, now: int) -> int | None:
        """Freeze the working copy for the owner's review. A newer submission replaces an open one."""
        with self.db.transaction() as c:
            row = c.execute("SELECT data, flags, status FROM personas WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            data, flags, status = row
            c.execute("DELETE FROM reviews WHERE user_id = ? AND decided_at IS NULL", (user_id,))
            cur = c.execute(
                "INSERT INTO reviews (user_id, data, flags, submitted_at) VALUES (?, ?, ?, ?)",
                (user_id, data, flags, now),
            )
            if status in ("draft", "rejected"):
                c.execute("UPDATE personas SET status = 'pending', updated_at = ? WHERE user_id = ?", (now, user_id))
            return int(cur.lastrowid or 0)

    def withdraw(self, user_id: int, now: int) -> bool:
        with self.db.transaction() as c:
            gone = c.execute("DELETE FROM reviews WHERE user_id = ? AND decided_at IS NULL", (user_id,)).rowcount
            c.execute(
                "UPDATE personas SET status = 'draft', updated_at = ? WHERE user_id = ? AND status = 'pending'",
                (now, user_id),
            )
            return bool(gone)

    def _reviews(self, c: sqlite3.Connection, where: str, args: tuple[Any, ...]) -> list[Review]:
        rows = c.execute(
            "SELECT r.id, r.user_id, u.handle, u.email, r.data, r.flags, r.submitted_at, r.decided_at, r.decision, "  # noqa: S608
            "r.note, p.live_data IS NOT NULL FROM reviews r JOIN users u ON u.id = r.user_id "
            f"JOIN personas p ON p.user_id = r.user_id WHERE {where}",
            args,
        ).fetchall()
        return [
            Review(
                id=row[0],
                user_id=row[1],
                handle=row[2],
                email=row[3],
                data=json.loads(row[4]),
                flags=json.loads(row[5]),
                submitted_at=row[6],
                decided_at=row[7],
                decision=row[8],
                note=row[9],
                live_before=bool(row[10]),
            )
            for row in rows
        ]

    def open_reviews(self) -> list[Review]:
        with self.db.reading() as c:
            return self._reviews(c, "r.decided_at IS NULL ORDER BY r.submitted_at, r.id", ())

    def get_review(self, review_id: int) -> Review | None:
        with self.db.reading() as c:
            found = self._reviews(c, "r.id = ?", (review_id,))
        return found[0] if found else None

    def open_review_for(self, user_id: int) -> Review | None:
        with self.db.reading() as c:
            found = self._reviews(c, "r.user_id = ? AND r.decided_at IS NULL ORDER BY r.id DESC", (user_id,))
        return found[0] if found else None

    def latest_review(self, user_id: int) -> Review | None:
        with self.db.reading() as c:
            found = self._reviews(c, "r.user_id = ? ORDER BY r.id DESC LIMIT 1", (user_id,))
        return found[0] if found else None

    def decide(self, review_id: int, decision: Decision, note: str, now: int) -> Review | None:
        """Approve (the submitted copy goes live) or reject (with a note for the member)."""
        with self.db.transaction() as c:
            found = self._reviews(c, "r.id = ? AND r.decided_at IS NULL", (review_id,))
            if not found:
                return None
            review = found[0]
            c.execute(
                "UPDATE reviews SET decided_at = ?, decision = ?, note = ? WHERE id = ?",
                (now, decision, note, review_id),
            )
            if decision == "approved":
                # A member who paused their page stays paused; the new version shows when they resume.
                c.execute(
                    "UPDATE personas SET live_data = ?, published_at = ?, updated_at = ?, "
                    "status = CASE WHEN status = 'paused' THEN 'paused' ELSE 'live' END WHERE user_id = ?",
                    (_dump(review.data), now, now, review.user_id),
                )
            else:
                c.execute(
                    "UPDATE personas SET status = 'rejected', updated_at = ? WHERE user_id = ? AND status = 'pending'",
                    (now, review.user_id),
                )
        return review

    def review_count(self) -> int:
        with self.db.reading() as c:
            return int(c.execute("SELECT COUNT(*) FROM reviews WHERE decided_at IS NULL").fetchone()[0])

    # Export

    def export(self, user_id: int) -> dict[str, Any] | None:
        """Everything stored about a member, except secrets (password hash, session ids)."""
        user = self.get_user(user_id)
        if user is None:
            return None
        persona = self.get_persona(user_id)
        with self.db.reading() as c:
            reviews = c.execute(
                "SELECT submitted_at, decided_at, decision, note FROM reviews WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            request = (
                c.execute(
                    "SELECT created_at, name, email, portfolio_url, about, reason, status, decided_at "
                    "FROM access_requests WHERE id = ?",
                    (user.request_id,),
                ).fetchone()
                if user.request_id is not None
                else None
            )
        return {
            "account": {
                "handle": user.handle,
                "email": user.email,
                "name": user.name,
                "status": user.status,
                "created_at": user.created_at,
                "last_active_at": user.last_active_at,
            },
            "access_request": dict(
                zip(
                    ("created_at", "name", "email", "portfolio_url", "about", "reason", "status", "decided_at"),
                    request,
                    strict=True,
                )
            )
            if request
            else None,
            "persona": {
                "status": persona.status,
                "show_in_search": persona.show_in_search,
                "working_copy": persona.data,
                "live_version": persona.live_data,
                "flags": persona.flags,
                "updated_at": persona.updated_at,
                "published_at": persona.published_at,
            }
            if persona
            else None,
            "reviews": [
                {"submitted_at": s, "decided_at": d, "decision": dec, "note": note} for s, d, dec, note in reviews
            ],
            "files": [
                {
                    "name": f.original_name,
                    "kind": f.kind,
                    "type": f.mime,
                    "size": f.size,
                    "uploaded_at": f.created_at,
                    "path_in_zip": f"files/{f.id}-{f.stored_name}",
                    "extracted_text": f.text,
                }
                for f in self.list_files(user_id)
            ],
        }
