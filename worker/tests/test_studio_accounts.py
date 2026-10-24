"""Member accounts: joining with an invite, handles, sign-in, lockout, sessions, CSRF and password resets."""

import re
import time
from dataclasses import replace

import pytest

from openfolio_worker.cloud.profile import handle_problem

from cloud_helpers import approve, client_for, login, rows, submit
from studio_helpers import (
    PASSWORD,
    app_for,
    browser,
    csrf,
    db_exec,
    db_rows,
    form_token,
    invite,
    join,
    owner,
)


@pytest.fixture
def app(cloud_settings):
    return app_for(cloud_settings)


def post_join(client, token, handle="jane", password=PASSWORD, **extra):
    data = {"form_token": form_token(client, f"/join/{token}"), "handle": handle, "password": password, **extra}
    return client.post(f"/join/{token}", data=data)


def test_signup_with_a_real_approval_creates_the_account_and_uses_the_invite(cloud_settings):
    client = client_for(cloud_settings)
    submit(client)
    login(client)
    token = approve(client, cloud_settings)
    page = client.get(f"/join/{token}")
    assert page.status_code == 200
    assert 'value="jane@example.com" readonly' in page.text
    assert 'value="jane-doe"' in page.text  # suggested from the name
    r = post_join(client, token, handle="jane")
    assert r.status_code == 303
    assert r.headers["location"] == "/studio/setup?welcome=1"
    cookie = r.headers["set-cookie"]
    assert "openfolio_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=604800" in cookie
    assert rows(cloud_settings, "SELECT handle, email, status FROM users") == [("jane", "jane@example.com", "active")]
    assert rows(cloud_settings, "SELECT used_at IS NOT NULL FROM invites") == [(1,)]
    assert rows(cloud_settings, "SELECT handle, status FROM personas") == [("jane", "draft")]
    setup = client.get("/studio/setup?m=welcome")
    assert setup.status_code == 200
    assert "Let's draft your AI" in setup.text
    assert "Content-Security-Policy" in setup.headers
    assert "'unsafe-inline'" not in setup.headers["content-security-policy"]


def test_a_used_invite_cannot_create_a_second_account(app, cloud_settings):
    token = invite(cloud_settings)
    first = browser(app)
    assert post_join(first, token).status_code == 303
    second = browser(app)
    page = second.get(f"/join/{token}")
    assert page.status_code == 404
    assert "This link isn't valid." in page.text
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM users") == [(1,)]


def test_an_expired_invite_is_refused(app, cloud_settings):
    token = invite(cloud_settings, expires_in=-1)
    client = browser(app)
    assert client.get(f"/join/{token}").status_code == 404
    # Even with a token from another page, the expired invite can't be used.
    other = invite(cloud_settings, "other@example.com")
    data = {"form_token": form_token(client, f"/join/{other}"), "handle": "jane", "password": PASSWORD}
    assert client.post(f"/join/{token}", data=data).status_code == 404
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM users") == [(0,)]


@pytest.mark.parametrize(
    ("handle", "ok"),
    [
        ("jane", True),
        ("jane-doe-2", True),
        ("ab", False),  # too short
        ("a" * 31, False),
        ("-jane", False),
        ("jane-", False),
        ("Jane", False),
        ("jane_doe", False),
        ("jané", False),
        ("admin", False),
        ("studio", False),
        ("api", False),
        ("embed", False),
        ("avatars", False),
        ("login", False),
        ("static", False),
        ("faisal", False),  # a file persona's id
    ],
)
def test_handle_rules(handle, ok):
    assert (handle_problem(handle, frozenset({"faisal"})) is None) is ok


def test_join_shows_field_errors_and_keeps_the_invite(app, cloud_settings):
    token = invite(cloud_settings)
    client = browser(app)
    r = post_join(client, token, handle="admin", password="short")
    assert r.status_code == 400
    assert "That handle is taken" in r.text
    assert "Use at least 12 characters." in r.text
    r = post_join(client, token, handle="faisal")
    assert r.status_code == 400  # the file persona's id is reserved
    join(app, cloud_settings, handle="taken")
    r = post_join(client, token, handle="taken")
    assert r.status_code == 400
    assert db_rows(cloud_settings, "SELECT used_at FROM invites WHERE request_id = 1") == [(None,)]


def test_one_account_per_email(app, cloud_settings):
    join(app, cloud_settings, handle="jane", email="jane@example.com")
    token = invite(cloud_settings, "jane@example.com")
    r = post_join(browser(app), token, handle="jane2")
    assert r.status_code == 409
    assert "already exists" in r.text


def sign_in(client, email="jane@example.com", password=PASSWORD):
    return client.post(
        "/login", data={"form_token": form_token(client, "/login"), "email": email, "password": password}
    )


def test_login_logout_and_generic_errors(app, cloud_settings):
    join(app, cloud_settings, handle="jane", email="jane@example.com")
    client = browser(app)
    wrong_password = sign_in(client, password="not the password!!")
    unknown_email = sign_in(client, email="nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert "That email and password don&#39;t match." in wrong_password.text
    assert "That email and password don&#39;t match." in unknown_email.text
    r = sign_in(client)
    assert r.status_code == 303
    assert r.headers["location"] == "/studio"
    assert client.get("/studio/account").status_code == 200
    out = client.post("/logout", data={"csrf": csrf(client)})
    assert out.status_code == 303
    assert client.get("/studio/account").status_code == 303  # back to /login


def test_member_login_lockout_is_separate_from_the_owner(app, cloud_settings):
    join(app, cloud_settings, handle="jane", email="jane@example.com")
    client = browser(app)
    for _ in range(5):
        assert sign_in(client, password="wrong password!!").status_code == 401
    locked = sign_in(client)  # even the right password waits out the lockout
    assert locked.status_code == 429
    assert "Too many attempts" in locked.text
    owner(app)  # the owner's sign-in is counted separately


def test_logout_revokes_the_session_server_side(app, cloud_settings):
    client = join(app, cloud_settings)
    cookie = client.cookies.get("openfolio_session")
    client.post("/logout", data={"csrf": csrf(client)})
    thief = browser(app)
    thief.cookies.set("openfolio_session", cookie)
    assert thief.get("/studio/account").status_code == 303
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM user_sessions") == [(0,)]


def test_password_change_signs_out_other_devices(app, cloud_settings):
    laptop = join(app, cloud_settings, handle="jane", email="jane@example.com")
    phone = browser(app)
    assert sign_in(phone).status_code == 303
    bad = laptop.post("/studio/account/password", data={"csrf": csrf(laptop), "current": "nope", "password": "x" * 12})
    assert bad.status_code == 400
    assert "That isn&#39;t your current password." in bad.text
    r = laptop.post(
        "/studio/account/password",
        data={"csrf": csrf(laptop), "current": PASSWORD, "password": "a brand new long password"},
    )
    assert r.status_code == 303
    assert laptop.get("/studio/account").status_code == 200
    assert phone.get("/studio/account").status_code == 303
    assert sign_in(browser(app), password="a brand new long password").status_code == 303


def test_forged_session_cookies_are_ignored(app, cloud_settings):
    join(app, cloud_settings)
    thief = browser(app)
    thief.cookies.set("openfolio_session", "x" * 40)
    assert thief.get("/studio").status_code == 303
    assert thief.get("/studio/setup").headers["location"] == "/login"


def test_csrf_and_origin_checks_on_member_forms(app, cloud_settings):
    client = join(app, cloud_settings)
    assert client.post("/studio/profile", data={"name": "Mallory"}).status_code == 403
    assert client.post("/studio/profile", data={"name": "Mallory", "csrf": "forged"}).status_code == 403
    r = client.post(
        "/studio/profile", data={"name": "Mallory", "csrf": csrf(client)}, headers={"origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert client.post("/studio/account/delete", data={"confirm": "jane"}).status_code == 403
    assert client.post("/logout", data={}).status_code == 403
    files = {"file": ("a.txt", b"hello world", "text/plain")}
    assert client.post("/studio/files", data={"slot": "document"}, files=files).status_code == 403
    # Signed-out forms need the double-submit token too.
    anon = browser(app)
    assert anon.post("/login", data={"email": "jane@example.com", "password": PASSWORD}).status_code == 403
    token = invite(cloud_settings, "new@example.com")
    assert anon.post(f"/join/{token}", data={"handle": "newbie", "password": PASSWORD}).status_code == 403
    assert db_rows(cloud_settings, "SELECT name FROM users") == [("Jane Doe",)]


def test_studio_requires_sign_in(app):
    anon = browser(app)
    for path in (
        "/studio",
        "/studio/setup",
        "/studio/profile",
        "/studio/preview",
        "/studio/publish",
        "/studio/account",
    ):
        r = anon.get(path)
        assert r.status_code == 303, path
        assert r.headers["location"] == "/login"
    assert anon.get("/studio/draft/status").status_code == 401
    assert anon.get("/studio/account/export").status_code == 303


def test_paused_members_cannot_sign_in(app, cloud_settings):
    client = join(app, cloud_settings, handle="jane", email="jane@example.com")
    db_exec(cloud_settings, "UPDATE users SET status = 'paused'")
    assert client.get("/studio/account").status_code == 303
    r = sign_in(browser(app))
    assert r.status_code == 403
    assert "paused" in r.text


class Outbox:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        return True


@pytest.fixture
def mail_app(cloud_settings, monkeypatch):
    from openfolio_worker.config import SmtpSettings

    smtp = SmtpSettings(host="smtp.example.com", port=587, sender="o@example.com", user=None, password=None)
    settings = replace(cloud_settings, cloud=replace(cloud_settings.cloud, smtp=smtp))
    app = app_for(settings)
    outbox = Outbox()
    monkeypatch.setattr(app.state.cloud.mailer, "send", outbox.send)
    return app, settings, outbox


def test_password_reset_by_email_is_single_use_and_never_enumerates(mail_app):
    app, settings, outbox = mail_app
    jane = join(app, settings, handle="jane", email="jane@example.com")
    client = browser(app)
    known = client.post(
        "/login/forgot", data={"form_token": form_token(client, "/login/forgot"), "email": "jane@example.com"}
    )
    unknown = client.post(
        "/login/forgot", data={"form_token": form_token(client, "/login/forgot"), "email": "x@example.com"}
    )
    assert known.status_code == unknown.status_code == 303
    assert known.headers["location"] == unknown.headers["location"] == "/login/forgot?sent=1"
    assert len(outbox.sent) == 1
    to, _subject, body = outbox.sent[0]
    assert to == "jane@example.com"
    link = re.search(r"http://127\.0\.0\.1:7872(/login/reset/[A-Za-z0-9_-]+)", body).group(1)
    stored = db_rows(settings, "SELECT token_hash, expires_at - created_at FROM password_resets")
    assert len(stored) == 1
    assert link.rsplit("/", 1)[1] not in stored[0][0]  # only a hash is kept
    assert stored[0][1] == 3600
    page = client.get(link)
    assert page.status_code == 200
    r = client.post(link, data={"form_token": form_token(client, link), "password": "my new long password"})
    assert r.status_code == 303
    assert r.headers["location"] == "/login?m=reset"
    assert client.get(link).status_code == 404  # single use
    assert jane.get("/studio/account").status_code == 303  # every session signed out
    assert sign_in(browser(app), password="my new long password").status_code == 303


def test_reset_links_expire(mail_app):
    app, settings, outbox = mail_app
    join(app, settings, handle="jane", email="jane@example.com")
    client = browser(app)
    client.post("/login/forgot", data={"form_token": form_token(client, "/login/forgot"), "email": "jane@example.com"})
    link = re.search(r"(/login/reset/[A-Za-z0-9_-]+)", outbox.sent[0][2]).group(1)
    db_exec(settings, "UPDATE password_resets SET expires_at = ?", int(time.time()) - 1)
    assert client.get(link).status_code == 404


def test_forgot_without_email_gives_the_same_answer(app, cloud_settings):
    join(app, cloud_settings, handle="jane", email="jane@example.com")
    client = browser(app)
    r = client.post(
        "/login/forgot", data={"form_token": form_token(client, "/login/forgot"), "email": "jane@example.com"}
    )
    assert r.status_code == 303
    page = client.get("/login/forgot?sent=1")
    assert "ask the site owner" in page.text
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM password_resets") == [(0,)]
