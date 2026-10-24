"""Helpers shared by the cloud page tests."""

import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from openfolio_worker.config import Settings
from openfolio_worker.server import create_app

from conftest import ADMIN_PASSWORD

VALID = {
    "name": "Jane Doe",
    "email": "Jane@Example.com",
    "portfolio_url": "https://jane.dev",
    "about": "Product designer",
    "reason": "I want recruiters to hear my story.",
    "consent": "on",
}


def client_for(settings: Settings, transport=None) -> TestClient:
    return TestClient(create_app(settings, transport=transport), follow_redirects=False)


def rows(settings: Settings, sql: str, *args) -> list[tuple]:
    conn = sqlite3.connect(Path(settings.data_dir) / "cloud.db")
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def submit(client: TestClient, **changes) -> object:
    return client.post("/cloud/requests", data={**VALID, **changes})


def login(client: TestClient) -> str:
    r = client.post("/admin/login", data={"password": ADMIN_PASSWORD})
    assert r.status_code == 303, r.text
    return csrf(client)


def csrf(client: TestClient) -> str:
    page = client.get("/admin")
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def request_id(settings: Settings, email: str = "jane@example.com") -> int:
    return rows(settings, "SELECT id FROM access_requests WHERE email = ?", email)[0][0]


def approve(client: TestClient, settings: Settings, email: str = "jane@example.com") -> str:
    """Approve a request and return the invite token from the one-time banner."""
    token = csrf(client)
    r = client.post(f"/admin/requests/{request_id(settings, email)}/approve", data={"csrf": token})
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    link = re.search(r'id="invite-link"[^>]*value="([^"]+)"', page.text).group(1)
    return link.rsplit("/", 1)[1]
