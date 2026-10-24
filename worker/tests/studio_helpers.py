"""Helpers for the Studio tests: members, forms, generated documents and photos."""

import hashlib
import io
import re
import secrets
import sqlite3
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from openfolio_worker.config import Settings
from openfolio_worker.server import create_app

from cloud_helpers import login

PASSWORD = "a long and lovely password"
PROFILE = {
    "name": "Jane Doe",
    "first_name": "Jane",
    "title": "Senior Product Designer",
    "tagline": "I design calm checkout flows that convert.",
    "about": "I lead design for payments at Acme. I care about clarity and measurable results.",
    "highlights": "Raised checkout conversion by 18%\nBuilt the Acme design system",
    "experience-0-title": "Senior Product Designer",
    "experience-0-company": "Acme",
    "experience-0-period": "2021 to present",
    "experience-0-summary": "Lead designer for payments.",
    "projects-0-name": "Checkout redesign",
    "projects-0-org": "Acme",
    "projects-0-period": "2024",
    "projects-0-summary": "Rebuilt checkout end to end.",
    "projects-0-metric": "Conversion up 18%",
    "projects-0-url": "https://jane.dev/checkout",
    "skills-0-group": "Design",
    "skills-0-items": "Figma, Prototyping, Design systems",
    "links-0-label": "LinkedIn",
    "links-0-url": "https://linkedin.com/in/janedoe",
    "quick-0-label": "Projects",
    "quick-0-question": "What are you proudest of building?",
    "email": "jane@jane.dev",
    "body": "F",
    "voice": "",
}


def app_for(settings: Settings, transport=None):
    return create_app(settings, transport=transport)


def browser(app) -> TestClient:
    return TestClient(app, follow_redirects=False)


def db_rows(settings: Settings, sql: str, *args) -> list[tuple]:
    conn = sqlite3.connect(Path(settings.data_dir) / "cloud.db")
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def db_exec(settings: Settings, sql: str, *args) -> None:
    conn = sqlite3.connect(Path(settings.data_dir) / "cloud.db")
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def invite(
    settings: Settings, email: str = "jane@example.com", name: str = "Jane Doe", *, expires_in: int = 3600
) -> str:
    """An approved request with a fresh invite, written straight to the database (the app must exist)."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn = sqlite3.connect(Path(settings.data_dir) / "cloud.db")
    try:
        cur = conn.execute(
            "INSERT INTO access_requests (created_at, name, email, portfolio_url, about, reason, status, decided_at,"
            " ip_hash) VALUES (?, ?, ?, 'https://example.com', 'Designer', '', 'approved', ?, 'test')",
            (now, name, email, now),
        )
        conn.execute(
            "INSERT INTO invites (request_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (cur.lastrowid, hashlib.sha256(token.encode()).hexdigest(), now, now + expires_in),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def form_token(client: TestClient, path: str) -> str:
    page = client.get(path)
    assert page.status_code in (200, 400), page.status_code
    return re.search(r'name="form_token" value="([^"]+)"', page.text).group(1)


def join(app, settings: Settings, handle: str = "jane", name: str = "Jane Doe", email: str | None = None) -> TestClient:
    """A signed-in member in their own browser."""
    token = invite(settings, email or f"{handle}@example.com", name)
    client = browser(app)
    data = {"form_token": form_token(client, f"/join/{token}"), "handle": handle, "password": PASSWORD}
    r = client.post(f"/join/{token}", data=data)
    assert r.status_code == 303, r.text
    return client


def csrf(client: TestClient) -> str:
    page = client.get("/studio/account")
    assert page.status_code == 200, page.status_code
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def owner(app) -> TestClient:
    client = browser(app)
    login(client)
    return client


def upload(client: TestClient, slot: str, filename: str, data: bytes, mime: str = "application/octet-stream"):
    return client.post(
        "/studio/files", data={"csrf": csrf(client), "slot": slot}, files={"file": (filename, data, mime)}
    )


def save_profile(client: TestClient, **changes: str):
    return client.post("/studio/profile", data={**PROFILE, **changes, "csrf": csrf(client)})


def make_ready(client: TestClient, **changes: str) -> None:
    """Photo plus a complete profile, ready to submit."""
    assert upload(client, "photo", "me.png", png()).status_code == 303
    r = save_profile(client, **changes)
    assert r.status_code == 303, r.text


def submit(client: TestClient):
    return client.post("/studio/publish/submit", data={"csrf": csrf(client)})


def png(width: int = 300, height: int = 200, color=(200, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def make_pdf(pages: list[str]) -> bytes:
    """A small valid PDF with one line of Helvetica text per page."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {5 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(paragraphs: list[str] | None = None, document_xml: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        if document_xml is None:
            body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs or [])
            document_xml = f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()
