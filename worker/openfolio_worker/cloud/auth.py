"""Owner authentication: scrypt password hashes, signed session cookies and CSRF tokens.

There is no server-side session store: the cookie carries a session id and its issue time, signed
with SESSION_SECRET (changing the secret signs everyone out). Logout records the id as revoked.
This module has no project imports because config.py validates ADMIN_PASSWORD_HASH with it.
"""

from __future__ import annotations

import base64
import binascii
import getpass
import hashlib
import hmac
import json
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Any

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_BYTES = 32
MAX_SCRYPT_N = 2**20  # a pasted hash must not make every login allocate gigabytes
MIN_PASSWORD_LENGTH = 12
SESSION_SECONDS = 12 * 3600
CLOCK_SKEW_SECONDS = 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    # OpenSSL needs about 128 * r * (n + p) bytes; leave headroom so valid parameters never fail.
    maxmem = 256 * r * (n + p) + 2**20
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=length)


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    """Return "scrypt$N$r$p$salt_b64$hash_b64" for ADMIN_PASSWORD_HASH."""
    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt, n, r, p, SCRYPT_KEY_BYTES)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(key)}"


def parse_password_hash(encoded: str) -> tuple[int, int, int, bytes, bytes]:
    """Split and sanity-check a hash. The ValueError reason never repeats the hash itself."""
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise ValueError("expected the format scrypt$N$r$p$salt$hash")
    try:
        n, r, p = (int(x) for x in parts[1:4])
        salt, key = _unb64(parts[4]), _unb64(parts[5])
    except (ValueError, binascii.Error) as e:
        raise ValueError("N, r and p must be numbers, and salt and hash base64") from e
    if n < 2 or n & (n - 1) or n > MAX_SCRYPT_N or not 1 <= r <= 32 or not 1 <= p <= 16:
        raise ValueError("scrypt parameters are out of range")
    if len(salt) < 8 or len(key) < 16:
        raise ValueError("salt or hash is too short")
    return n, r, p, salt, key


def verify_password(password: str, encoded: str) -> bool:
    n, r, p, salt, key = parse_password_hash(encoded)
    return hmac.compare_digest(_scrypt(password, salt, n, r, p, len(key)), key)


def hash_token(token: str) -> str:
    """Invite tokens are stored only as this digest, so a copy of the database cannot be used to sign up."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    sid: str
    issued_at: int


class Keys:
    """Purpose-bound HMAC keys from SESSION_SECRET: a value signed for one use never verifies as another."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def _mac(self, purpose: str, data: bytes) -> bytes:
        key = hmac.new(self._secret, purpose.encode(), hashlib.sha256).digest()
        return hmac.new(key, data, hashlib.sha256).digest()

    def ip_hash(self, ip: str) -> str:
        """Salted IP digest: enough to rate-limit and spot abuse, without storing the address."""
        return self._mac("ip", ip.encode()).hex()[:32]

    def sign(self, purpose: str, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return f"{_b64(body)}.{_b64(self._mac(purpose, body))}"

    def unsign(self, purpose: str, value: str | None) -> dict[str, Any] | None:
        if not value or value.count(".") != 1 or len(value) > 4096:
            return None
        body_b64, mac_b64 = value.split(".")
        try:
            body, mac = _unb64(body_b64), _unb64(mac_b64)
        except (ValueError, binascii.Error):
            return None
        if not hmac.compare_digest(mac, self._mac(purpose, body)):
            return None
        try:
            payload = json.loads(body)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def new_session(self, now: float | None = None) -> tuple[str, Session]:
        session = Session(sid=secrets.token_urlsafe(16), issued_at=int(time.time() if now is None else now))
        return self.sign("session", {"sid": session.sid, "iat": session.issued_at}), session

    def read_session(self, cookie: str | None, now: float | None = None) -> Session | None:
        payload = self.unsign("session", cookie)
        if not payload:
            return None
        sid, issued = payload.get("sid"), payload.get("iat")
        if not isinstance(sid, str) or not isinstance(issued, int) or isinstance(issued, bool):
            return None
        current = time.time() if now is None else now
        if not issued - CLOCK_SKEW_SECONDS <= current <= issued + SESSION_SECONDS:
            return None
        return Session(sid=sid, issued_at=issued)

    def csrf_token(self, session: Session) -> str:
        # Bound to the session id, so a token from another or an old session never passes.
        return _b64(self._mac("csrf", session.sid.encode()))

    def check_csrf(self, session: Session, token: str | None) -> bool:
        if not token:
            return False
        return hmac.compare_digest(self.csrf_token(session).encode(), token.encode())


def main() -> None:
    """openfolio-admin-hash: read a password from stdin and print a value for ADMIN_PASSWORD_HASH."""
    if sys.stdin.isatty():
        password = getpass.getpass("Admin password: ")
        if getpass.getpass("Repeat it: ") != password:
            sys.exit("The passwords don't match.")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    print(hash_password(password))
