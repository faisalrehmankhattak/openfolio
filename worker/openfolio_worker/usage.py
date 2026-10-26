"""Usage metering and spending caps.

Every call and AI draft adds to daily totals in SQLite (DATA_DIR/usage.db, UTC days), kept for three
scopes: the whole server, each persona, and each visitor (an IP address hashed with a secret salt).
New calls are refused once a cap is reached, and a call in progress ends politely (see bot.py).

Totals are written while a call runs, so the caps can be exceeded by at most the calls already in
progress: MAX_SESSIONS x SESSION_MAX_MINUTES.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Limits

SERVER = "all"
METRICS = ("calls", "seconds", "llm_in", "llm_out", "tts_chars", "cost_usd")

TODAY_FULL = "Usage limit reached for today. Please try again tomorrow."
MONTH_FULL = "Usage limit reached for this month. Please try again later."
PERSONA_FULL = "This assistant has reached its usage limit for today. Please try again tomorrow."
VISITOR_FULL = "You've reached today's call limit. Please come back tomorrow."


@dataclass(frozen=True)
class Refusal:
    status: int  # 503 for a cap on the service, 429 for one visitor
    message: str


def persona_scope(persona_id: str) -> str:
    return f"persona:{persona_id}"


def visitor_scope(visitor: str) -> str:
    return f"visitor:{visitor}"


class UsageLedger:
    def __init__(
        self,
        path: Path,
        limits: Limits,
        *,
        paid_voice: bool = False,
        metered_stt: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.limits = limits
        self.paid_voice = paid_voice
        self.metered_stt = metered_stt
        self.clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, scope TEXT NOT NULL, metric TEXT NOT NULL,"
            " amount REAL NOT NULL DEFAULT 0, PRIMARY KEY (day, scope, metric))"
        )
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._salt = self._meta("salt") or self._set_meta("salt", secrets.token_hex(16))

    def _meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _set_meta(self, key: str, value: str) -> str:
        self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        return value

    def close(self) -> None:
        self._db.close()

    def visitor_key(self, ip: str) -> str:
        """A stable, salted hash: totals per visitor without storing addresses."""
        return hashlib.sha256(f"{self._salt}:{ip}".encode()).hexdigest()[:16]

    def _day(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).strftime("%Y-%m-%d")

    # Recording

    def add(self, persona_id: str, visitor: str | None, metric: str, amount: float) -> None:
        if amount <= 0:
            return
        scopes = [SERVER, persona_scope(persona_id)] + ([visitor_scope(visitor)] if visitor else [])
        day = self._day()
        with self._lock:
            self._db.executemany(
                "INSERT INTO usage (day, scope, metric, amount) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (day, scope, metric) DO UPDATE SET amount = amount + excluded.amount",
                [(day, scope, metric, amount) for scope in scopes],
            )

    def add_call(self, persona_id: str, visitor: str | None) -> None:
        self.add(persona_id, visitor, "calls", 1)

    def add_seconds(self, persona_id: str, visitor: str | None, seconds: float) -> None:
        self.add(persona_id, visitor, "seconds", seconds)
        if self.metered_stt:
            self.add(persona_id, visitor, "cost_usd", seconds / 60 * self.limits.price_stt_per_minute)

    def add_llm(self, persona_id: str, visitor: str | None, prompt_tokens: int, completion_tokens: int) -> None:
        lim = self.limits
        self.add(persona_id, visitor, "llm_in", prompt_tokens)
        self.add(persona_id, visitor, "llm_out", completion_tokens)
        cost = (prompt_tokens * lim.price_llm_input_per_mtok + completion_tokens * lim.price_llm_output_per_mtok) / 1e6
        self.add(persona_id, visitor, "cost_usd", cost)

    def add_tts(self, persona_id: str, visitor: str | None, characters: int) -> None:
        if not self.paid_voice:
            return  # the local voice costs nothing per character
        self.add(persona_id, visitor, "tts_chars", characters)
        self.add(persona_id, visitor, "cost_usd", characters * self.limits.price_tts_per_mchar / 1e6)

    # Reading

    def total(self, scope: str, metric: str, period: str = "day") -> float:
        day = self._day()
        if period == "day":
            query, arg = "SELECT SUM(amount) FROM usage WHERE day = ? AND scope = ? AND metric = ?", day
        else:
            query, arg = "SELECT SUM(amount) FROM usage WHERE day LIKE ? AND scope = ? AND metric = ?", day[:7] + "-%"
        with self._lock:
            row = self._db.execute(query, (arg, scope, metric)).fetchone()
        return float(row[0] or 0)

    def server_cap(self) -> str | None:
        """The message for the first whole-server cap reached, if any."""
        lim = self.limits

        def over(metric: str, period: str, cap: float, scale: float = 1) -> bool:
            return cap > 0 and self.total(SERVER, metric, period) / scale >= cap

        tokens_day = self.total(SERVER, "llm_in") + self.total(SERVER, "llm_out")
        tokens_month = self.total(SERVER, "llm_in", "month") + self.total(SERVER, "llm_out", "month")
        if (
            over("cost_usd", "month", lim.monthly_budget_usd)
            or over("seconds", "month", lim.monthly_max_minutes, 60)
            or over("tts_chars", "month", lim.monthly_max_tts_chars)
            or (lim.monthly_max_llm_tokens > 0 and tokens_month >= lim.monthly_max_llm_tokens)
        ):
            return MONTH_FULL
        if (
            over("cost_usd", "day", lim.daily_budget_usd)
            or over("seconds", "day", lim.daily_max_minutes, 60)
            or over("tts_chars", "day", lim.daily_max_tts_chars)
            or (lim.daily_max_llm_tokens > 0 and tokens_day >= lim.daily_max_llm_tokens)
        ):
            return TODAY_FULL
        return None

    def refusal(self, persona_id: str, visitor: str | None) -> Refusal | None:
        """Why a new call can't start, or None."""
        if message := self.server_cap():
            return Refusal(503, message)
        cap = self.limits.persona_minutes_per_day
        if cap > 0 and self.total(persona_scope(persona_id), "seconds") / 60 >= cap:
            return Refusal(503, PERSONA_FULL)
        calls = self.limits.visitor_calls_per_day
        if visitor and calls > 0 and self.total(visitor_scope(visitor), "calls") >= calls:
            return Refusal(429, VISITOR_FULL)
        return None

    def summary(self) -> dict[str, dict[str, float]]:
        """Server totals for today and this month, for the owner (no per-visitor data)."""
        return {
            period: {metric: round(self.total(SERVER, metric, period), 4) for metric in METRICS}
            for period in ("day", "month")
        }


def main() -> None:
    """openfolio-usage: today's and this month's spending against the caps."""
    from dataclasses import asdict

    from .config import load_settings

    settings = load_settings()
    ledger = UsageLedger(settings.data_dir / "usage.db", settings.limits)
    lim = settings.limits
    summary = ledger.summary()
    for period, budget, minutes in (
        ("day", lim.daily_budget_usd, lim.daily_max_minutes),
        ("month", lim.monthly_budget_usd, lim.monthly_max_minutes),
    ):
        s = summary[period]
        print(
            f"{period:>5}: ${s['cost_usd']:.2f} of ${budget:.2f}, {s['seconds'] / 60:.0f} of {minutes} min,"
            f" {s['calls']:.0f} calls, {s['llm_in'] + s['llm_out']:.0f} tokens"
        )
    print("limit: " + (ledger.server_cap() or "none reached"))
    print("caps:  " + ", ".join(f"{k}={v}" for k, v in asdict(lim).items()))
