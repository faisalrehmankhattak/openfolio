"""Run one parser in a separate, resource-limited process.

A hostile file (a decompression bomb, a PDF that loops forever, a parser bug) can at worst take
down this child: it gets a CPU-time cap, an address-space cap (RLIMIT_AS, enforced on Linux),
no child processes, a small file-size cap and a wall-clock timeout, and its environment holds no
secrets. The parent reads one JSON line from stdout.

    python -I -m openfolio_worker.cloud.sandbox <pdf|docx|text|photo> <input> [<output>]
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 20.0
MEMORY_BYTES = 1024 * 1024 * 1024
OUTPUT_BYTES = 20 * 1024 * 1024
MAX_STDOUT = 512 * 1024
KINDS = ("pdf", "docx", "text", "photo")


class SandboxError(Exception):
    """The parser refused the file (code from parsers.ParseError) or the process failed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _limit(resource_id: int, value: int) -> None:
    import resource

    with contextlib.suppress(ValueError, OSError):  # macOS refuses some limits; Linux enforces them
        resource.setrlimit(resource_id, (value, value))


def _apply_limits() -> None:
    import resource

    _limit(resource.RLIMIT_AS, MEMORY_BYTES)
    _limit(resource.RLIMIT_CPU, int(TIMEOUT_SECONDS) + 5)
    _limit(resource.RLIMIT_FSIZE, OUTPUT_BYTES)
    _limit(resource.RLIMIT_CORE, 0)
    if hasattr(resource, "RLIMIT_NPROC"):
        _limit(resource.RLIMIT_NPROC, 0)


def child(argv: Sequence[str]) -> int:
    _apply_limits()
    from . import parsers  # imported after the limits, like everything that touches the file

    kind, src = argv[0], Path(argv[1])
    try:
        if kind == "pdf":
            result = parsers.parse_pdf(src)
        elif kind == "docx":
            result = parsers.parse_docx(src)
        elif kind == "text":
            result = parsers.parse_text(src)
        elif kind == "photo":
            result = parsers.process_photo(src, Path(argv[2]))
        else:
            result = {"error": "unknown_kind"}
    except parsers.ParseError as e:
        result = {"error": e.code}
    except MemoryError:
        result = {"error": "too_complex"}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


def _command(kind: str, src: Path, out: Path | None) -> list[str]:
    args = [sys.executable, "-I", "-m", "openfolio_worker.cloud.sandbox", kind, str(src)]
    return [*args, str(out)] if out else args


def _clean_env() -> dict[str, str]:
    # No API keys, session secret or SMTP password in the child.
    keep = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    return {key: os.environ[key] for key in keep if key in os.environ}


async def run(
    kind: str,
    src: Path,
    out: Path | None = None,
    *,
    seconds: float = TIMEOUT_SECONDS,
    slots: asyncio.Semaphore | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    """Parse src in a child process within seconds. slots caps parallel parsers; command replaces the child in tests."""
    if kind not in KINDS:
        raise SandboxError("unknown_kind")
    async with slots or asyncio.Semaphore(1):
        proc = await asyncio.create_subprocess_exec(
            *(command or _command(kind, src, out)),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_clean_env(),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), seconds)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise SandboxError("timeout") from None
    if proc.returncode != 0 or not stdout or len(stdout) > MAX_STDOUT:
        # Killed by a limit (memory, CPU) or crashed: treat the file as too complex to read.
        raise SandboxError("too_complex")
    try:
        result = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise SandboxError("too_complex") from e
    if not isinstance(result, dict):
        raise SandboxError("too_complex")
    if "error" in result:
        raise SandboxError(str(result["error"]))
    return result


if __name__ == "__main__":
    sys.exit(child(sys.argv[1:]))
