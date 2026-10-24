import hashlib
import html
import time
from dataclasses import replace

import pytest

from openfolio_worker.cloud.admin import LOCKED_ERROR, LOGIN_ERROR
from openfolio_worker.cloud.auth import Keys

from cloud_helpers import approve, client_for, csrf, login, request_id, rows, submit
from conftest import ADMIN_PASSWORD, SESSION_SECRET

COOKIE = "openfolio_admin"


@pytest.fixture
def client(cloud_settings):
    return client_for(cloud_settings)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin"),
        ("get", "/admin?tab=approved"),
        ("post", "/admin/logout"),
        ("post", "/admin/requests/1/approve"),
        ("post", "/admin/requests/1/reject"),
        ("post", "/admin/requests/1/delete"),
    ],
)
def test_admin_routes_need_a_session(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_login_page_and_headers(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert 'type="password"' in r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert '<meta name="robots" content="noindex, nofollow">' in r.text


@pytest.mark.parametrize("password", ["wrong password", "", ADMIN_PASSWORD + " "])
def test_wrong_password_gets_one_message(client, password):
    r = client.post("/admin/login", data={"password": password})
    assert r.status_code == 401
    assert LOGIN_ERROR in html.unescape(r.text)
    assert COOKIE not in r.headers.get("set-cookie", "")


def test_lockout_after_five_failures(client, cloud_settings):
    for _ in range(5):
        assert client.post("/admin/login", data={"password": "nope"}).status_code == 401
    r = client.post("/admin/login", data={"password": ADMIN_PASSWORD})
    assert r.status_code == 429
    assert LOCKED_ERROR in r.text
    assert rows(cloud_settings, "SELECT COUNT(*) FROM audit_log WHERE action = 'login.failed'") == [(5,)]


def test_session_cookie_flags(client):
    r = client.post("/admin/login", data={"password": ADMIN_PASSWORD})
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"
    cookie = r.headers["set-cookie"].lower()
    for flag in ("httponly", "samesite=strict", "path=/", "max-age=43200"):
        assert flag in cookie
    assert "secure" not in cookie  # http://127.0.0.1 during development


def test_https_public_url_uses_a_secure_host_cookie(cloud_settings):
    s = replace(cloud_settings, cloud=replace(cloud_settings.cloud, public_url="https://of.example.com"))
    r = client_for(s).post("/admin/login", data={"password": ADMIN_PASSWORD})
    assert r.headers["set-cookie"].startswith("__Host-openfolio_admin=")
    assert "; secure" in r.headers["set-cookie"].lower()


def test_dashboard_after_login(client):
    login(client)
    r = client.get("/admin")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "Pending" in r.text
    assert "Approved" in r.text
    assert "Rejected" in r.text


def test_tampered_or_expired_cookie_is_rejected(client):
    login(client)
    good = client.cookies[COOKIE]
    body, mac = good.split(".")
    flipped = mac[:-2] + ("AA" if not mac.endswith("AA") else "BB")
    expired, _ = Keys(SESSION_SECRET).new_session(now=time.time() - 13 * 3600)
    other_secret, _ = Keys("another-secret-" + "y" * 32).new_session()
    for bad in (body + "." + flipped, body[:-2] + "x." + mac, "garbage", "", expired, other_secret):
        client.cookies.clear()
        client.cookies.set(COOKIE, bad)
        assert client.get("/admin").status_code == 303, bad
    client.cookies.clear()
    client.cookies.set(COOKIE, good)
    assert client.get("/admin").status_code == 200


def test_logout_revokes_the_session(client, cloud_settings):
    token = login(client)
    old = client.cookies[COOKIE]
    r = client.post("/admin/logout", data={"csrf": token})
    assert (r.status_code, r.headers["location"]) == (303, "/admin/login?out=1")
    assert "signed out" in client.get("/admin/login?out=1").text
    client.cookies.clear()
    client.cookies.set(COOKIE, old)  # a copied cookie stops working too
    assert client.get("/admin").status_code == 303


@pytest.mark.parametrize("bad", [None, "", "wrong-token"])
def test_csrf_missing_or_wrong_is_403(client, cloud_settings, bad):
    submit(client)
    login(client)
    data = {} if bad is None else {"csrf": bad}
    for action in ("approve", "reject", "delete"):
        assert client.post(f"/admin/requests/{request_id(cloud_settings)}/{action}", data=data).status_code == 403
    assert client.post("/admin/logout", data=data).status_code == 403
    assert rows(cloud_settings, "SELECT status FROM access_requests") == [("pending",)]


def test_csrf_token_from_another_session_is_403(cloud_settings):
    one, two = client_for(cloud_settings), client_for(cloud_settings)
    submit(one)
    login(one)
    token_two = login(two)
    r = one.post(f"/admin/requests/{request_id(cloud_settings)}/approve", data={"csrf": token_two})
    assert r.status_code == 403


def test_foreign_origin_is_refused(client, cloud_settings):
    submit(client)
    token = login(client)
    r = client.post(
        f"/admin/requests/{request_id(cloud_settings)}/approve",
        data={"csrf": token},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert (
        client.post(
            "/admin/login", data={"password": ADMIN_PASSWORD}, headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_approve_creates_a_hashed_single_invite(client, cloud_settings):
    submit(client)
    login(client)
    token = approve(client, cloud_settings)
    assert len(token) >= 43  # 32 random bytes, URL-safe
    ((stored_hash, created, expires, used),) = rows(
        cloud_settings, "SELECT token_hash, created_at, expires_at, used_at FROM invites"
    )
    assert stored_hash == hashlib.sha256(token.encode()).hexdigest()
    assert expires - created == 7 * 86400
    assert used is None
    db_dir = cloud_settings.data_dir
    raw = b"".join(p.read_bytes() for p in db_dir.glob("cloud.db*"))
    assert token.encode() not in raw
    assert rows(cloud_settings, "SELECT status FROM access_requests") == [("approved",)]
    assert ("request.approved",) in rows(cloud_settings, "SELECT action FROM audit_log")
    # Shown once: the next page view no longer has it.
    assert token not in client.get("/admin?tab=approved").text


def test_new_invite_replaces_the_old_one(client, cloud_settings):
    submit(client)
    login(client)
    first = approve(client, cloud_settings)
    second = approve(client, cloud_settings)
    assert client.get(f"/join/{first}").status_code == 404
    assert client.get(f"/join/{second}").status_code == 200


def test_invite_pages(client, cloud_settings):
    submit(client)
    login(client)
    token = approve(client, cloud_settings)
    valid = client.get(f"/join/{token}")
    assert valid.status_code == 200
    assert "Welcome, Jane" in valid.text
    assert 'value="jane@example.com" readonly' in valid.text
    assert valid.headers["referrer-policy"] == "same-origin"  # not to other sites, and the form's Origin survives
    assert valid.headers["cache-control"] == "no-store"
    assert client.get(f"/join/{token}").status_code == 200  # creating the account consumes it; viewing does not
    old = client.get(f"/invite/{token}", follow_redirects=False)  # links emailed by stage 1
    assert old.status_code == 303
    assert old.headers["location"] == f"/join/{token}"

    def invalid(path: str) -> None:
        r = client.get(path)
        assert r.status_code == 404
        assert "This link isn't valid." in r.text
        assert "Jane" not in r.text

    invalid("/join/garbage")
    invalid("/join/" + "A" * 43)
    invalid("/join/" + token + "x")
    hashed = hashlib.sha256(token.encode()).hexdigest()
    import sqlite3

    conn = sqlite3.connect(cloud_settings.data_dir / "cloud.db")
    conn.execute("UPDATE invites SET expires_at = ? WHERE token_hash = ?", (int(time.time()) - 1, hashed))
    conn.commit()
    invalid(f"/join/{token}")  # expired
    conn.execute(
        "UPDATE invites SET expires_at = ?, used_at = ? WHERE token_hash = ?",
        (int(time.time()) + 3600, int(time.time()), hashed),
    )
    conn.commit()
    invalid(f"/join/{token}")  # used
    conn.close()


def test_reject_revokes_the_invite(client, cloud_settings):
    submit(client)
    login(client)
    token = approve(client, cloud_settings)
    r = client.post(f"/admin/requests/{request_id(cloud_settings)}/reject", data={"csrf": csrf(client)})
    assert r.status_code == 303
    assert rows(cloud_settings, "SELECT status FROM access_requests") == [("rejected",)]
    assert rows(cloud_settings, "SELECT COUNT(*) FROM invites") == [(0,)]
    assert client.get(f"/join/{token}").status_code == 404
    assert "Rejected Jane Doe" in client.get(r.headers["location"]).text


def test_delete_removes_the_request_and_its_invites(client, cloud_settings):
    submit(client)
    login(client)
    approve(client, cloud_settings)
    rid = request_id(cloud_settings)
    r = client.post(f"/admin/requests/{rid}/delete", data={"csrf": csrf(client)})
    assert r.status_code == 303
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(0,)]
    assert rows(cloud_settings, "SELECT COUNT(*) FROM invites") == [(0,)]
    actions = [a for (a,) in rows(cloud_settings, "SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["request.created", "login", "request.approved", "request.deleted"]
    page = client.get("/admin")
    assert "Deleted the request from Jane Doe" in page.text
    assert "jane@example.com" not in page.text  # the audit log keeps no personal data


def test_unknown_request_or_action(client):
    token = login(client)
    r = client.post("/admin/requests/999/approve", data={"csrf": token})
    assert r.status_code == 303
    assert "no longer exists" in client.get(r.headers["location"]).text
    assert client.post("/admin/requests/999/explode", data={"csrf": token}).status_code == 404


def test_admin_page_escapes_request_text(client, cloud_settings):
    submit(
        client,
        name="<script>alert(1)</script>",
        about="<img src=x onerror=alert(2)>",
        reason="</dd><script>alert(3)</script>",
    )
    import sqlite3

    conn = sqlite3.connect(cloud_settings.data_dir / "cloud.db")
    conn.execute("UPDATE access_requests SET portfolio_url = 'javascript:alert(4)'")
    conn.commit()
    conn.close()
    login(client)
    html = client.get("/admin").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert 'href="javascript:' not in html  # unsafe schemes are shown as text, never as links
    assert "javascript:alert(4)" in html


def test_portfolio_links_are_safe(client):
    submit(client)
    login(client)
    html = client.get("/admin").text
    assert 'href="https://jane.dev" target="_blank" rel="noopener noreferrer nofollow"' in html


def test_audit_log_lists_the_latest_entries(client, cloud_settings):
    submit(client)
    for _ in range(2):
        client.post("/admin/login", data={"password": "nope"})
    login(client)
    html = client.get("/admin").text
    for label in ("New request", "Failed sign-in", "Signed in"):
        assert label in html
