"""Members' data: export, deletion, isolation between members (IDOR) and CSRF / sign-in on every POST."""

import io
import json
import re
import time
import zipfile

import pytest

from cloud_helpers import csrf as admin_csrf
from cloud_helpers import submit as request_access
from conftest import PUBLIC_URL
from studio_helpers import (
    PASSWORD,
    app_for,
    browser,
    csrf,
    db_exec,
    db_rows,
    form_token,
    join,
    make_pdf,
    make_ready,
    owner,
    png,
    submit,
    upload,
)

EVIL = {"origin": "https://evil.example"}


def user_id(settings, handle) -> int:
    return db_rows(settings, "SELECT id FROM users WHERE handle = ?", handle)[0][0]


def file_ids(settings, handle) -> list[int]:
    return [
        i for (i,) in db_rows(settings, "SELECT id FROM files WHERE user_id = ? ORDER BY id", user_id(settings, handle))
    ]


def sign_in(client, email, password=PASSWORD):
    data = {"form_token": form_token(client, "/login"), "email": email, "password": password}
    return client.post("/login", data=data)


def two_members(app, settings):
    """Jane (submitted, with a document, pasted text and a photo) and Bob (a draft with his own files)."""
    jane = join(app, settings, "jane")
    upload(jane, "document", "jane-cv.pdf", make_pdf(["Jane secret plans for Acme"]), "application/pdf")
    jane.post("/studio/text", data={"csrf": csrf(jane), "text": "Jane pasted note about payments"})
    make_ready(jane)
    assert submit(jane).status_code == 303
    bob = join(app, settings, "bob", name="Bob Stone")
    upload(bob, "document", "bob-notes.txt", b"Bob private notes about robots", "text/plain")
    upload(bob, "photo", "bob.png", png(color=(10, 20, 200)))
    return jane, bob


# Export


def test_export_has_all_and_only_the_members_own_data(cloud_settings):
    app = app_for(cloud_settings)
    jane, _bob = two_members(app, cloud_settings)
    r = jane.get("/studio/account/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="openfolio-jane.zip"'
    assert r.headers["cache-control"] == "no-store"
    uid = user_id(cloud_settings, "jane")
    stored = db_rows(cloud_settings, "SELECT id, stored_name FROM files WHERE user_id = ? ORDER BY id", uid)
    assert len(stored) == 3
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert names == {"data.json"} | {f"files/{i}-{name}" for i, name in stored}
        for i, name in stored:
            on_disk = (cloud_settings.data_dir / "users" / str(uid) / name).read_bytes()
            assert z.read(f"files/{i}-{name}") == on_disk
        raw = z.read("data.json")
        everything = b"".join(z.read(n) for n in names)
    data = json.loads(raw)
    assert data["account"]["handle"] == "jane"
    assert data["account"]["email"] == "jane@example.com"
    assert data["access_request"]["email"] == "jane@example.com"
    assert data["persona"]["working_copy"]["title"] == "Senior Product Designer"
    assert data["persona"]["status"] == "pending"
    assert len(data["reviews"]) == 1
    assert {f["path_in_zip"] for f in data["files"]} == names - {"data.json"}
    assert any("Jane secret plans" in f["extracted_text"] for f in data["files"])
    # No secrets and nothing of Bob's.
    for needle in (b"password", b"scrypt", b"sid", b"token", b"Bob", b"bob", b"robots"):
        assert needle not in raw, needle
    assert b"Bob private notes" not in everything
    assert db_rows(cloud_settings, "SELECT user_id FROM audit_log WHERE action = 'data.exported'") == [(uid,)]


def test_export_needs_sign_in(cloud_settings):
    app = app_for(cloud_settings)
    join(app, cloud_settings, "jane")
    r = browser(app).get("/studio/account/export")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


# Deletion by the member


def test_account_deletion_erases_everything(cloud_settings):
    app = app_for(cloud_settings)
    jane, bob = two_members(app, cloud_settings)
    admin = owner(app)
    rid = db_rows(cloud_settings, "SELECT id FROM reviews WHERE decided_at IS NULL")[0][0]
    assert admin.post(f"/admin/reviews/{rid}/approve", data={"csrf": admin_csrf(admin)}).status_code == 303
    uid, bob_id = user_id(cloud_settings, "jane"), user_id(cloud_settings, "bob")
    request_id = db_rows(cloud_settings, "SELECT request_id FROM users WHERE id = ?", uid)[0][0]
    phone = browser(app)
    assert sign_in(phone, "jane@example.com").status_code == 303
    admin.post(f"/admin/members/{uid}/reset", data={"csrf": admin_csrf(admin)})  # an open reset link
    jane_dir = cloud_settings.data_dir / "users" / str(uid)
    assert len(list(jane_dir.iterdir())) == 3
    assert browser(app).get("/p/jane").status_code == 200
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM user_sessions WHERE user_id = ?", uid) == [(2,)]
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM password_resets WHERE user_id = ?", uid) == [(1,)]

    wrong = jane.post("/studio/account/delete", data={"csrf": csrf(jane), "confirm": "bob"})
    assert wrong.status_code == 400
    assert "Type jane to confirm." in wrong.text
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM users") == [(2,)]

    r = jane.post("/studio/account/delete", data={"csrf": csrf(jane), "confirm": " Jane "})
    assert r.status_code == 303
    assert r.headers["location"] == "/login?m=deleted"
    assert 'openfolio_session=""' in r.headers["set-cookie"]
    for table, column in (
        ("users", "id"),
        ("personas", "user_id"),
        ("files", "user_id"),
        ("reviews", "user_id"),
        ("user_sessions", "user_id"),
        ("password_resets", "user_id"),
        ("audit_log", "user_id"),
    ):
        sql = f"SELECT COUNT(*) FROM {table} WHERE {column} = ?"  # noqa: S608 - fixed names
        assert db_rows(cloud_settings, sql, uid) == [(0,)], table
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM access_requests WHERE id = ?", request_id) == [(0,)]
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM invites WHERE request_id = ?", request_id) == [(0,)]
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM access_requests WHERE email = 'jane@example.com'") == [(0,)]
    assert not jane_dir.exists()
    assert db_rows(cloud_settings, "SELECT user_id, detail FROM audit_log WHERE action = 'user.deleted'") == [
        (None, "by the member")
    ]
    # Every device is signed out, the page and the AI are gone and the password no longer works.
    assert jane.get("/studio").status_code == 303
    assert phone.get("/studio").status_code == 303
    assert browser(app).get("/p/jane").status_code == 404
    assert browser(app).get("/v1/personas/jane").status_code == 404
    assert "jane" not in app.state.cloud.registry.live_ids
    assert sign_in(browser(app), "jane@example.com").status_code == 401
    # Bob is untouched.
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM files WHERE user_id = ?", bob_id) == [(2,)]
    assert len(list((cloud_settings.data_dir / "users" / str(bob_id)).iterdir())) == 2
    assert bob.get("/studio/account").status_code == 200


# Isolation between members


def test_a_member_can_never_reach_another_members_data(cloud_settings):
    app = app_for(cloud_settings)
    jane, bob = two_members(app, cloud_settings)
    jane_id = user_id(cloud_settings, "jane")
    jane_files = file_ids(cloud_settings, "jane")
    photo_id = db_rows(cloud_settings, "SELECT id FROM files WHERE user_id = ? AND kind = 'photo'", jane_id)[0][0]
    rid = db_rows(cloud_settings, "SELECT id FROM reviews WHERE user_id = ?", jane_id)[0][0]
    jane_before = db_rows(cloud_settings, "SELECT data, status FROM personas WHERE user_id = ?", jane_id)

    # Read: files, the photo before go-live, the preview persona, the review page.
    for fid in jane_files:
        assert bob.get(f"/studio/files/{fid}").status_code == 404
    assert bob.get(f"/p/jane/photo-{photo_id}.jpg").status_code == 404
    assert bob.get("/v1/personas/jane~preview", headers={"origin": PUBLIC_URL}).status_code == 404
    assert bob.get("/v1/personas/jane~preview/ice-servers", headers={"origin": PUBLIC_URL}).status_code == 404
    assert bob.get(f"/admin/reviews/{rid}").headers["location"] == "/admin/login"
    assert bob.get("/admin?tab=members").headers["location"] == "/admin/login"
    preview = bob.get("/studio/preview")
    assert 'data-persona="bob~preview"' in preview.text
    assert "jane" not in preview.text.lower()
    for page in ("/studio/setup", "/studio/profile", "/studio/publish", "/studio/account"):
        text = bob.get(page).text
        assert "Jane secret" not in text
        assert "jane-cv.pdf" not in text
        assert "calm checkout flows" not in text, page  # Jane's tagline

    # Change: ids in the URL or the form never select another member.
    for fid in jane_files:
        assert bob.post(f"/studio/files/{fid}/delete", data={"csrf": csrf(bob)}).status_code == 303
    r = bob.post(
        "/studio/profile",
        data={
            "csrf": csrf(bob),
            "name": "Bob Stone",
            "title": "Robot whisperer",
            "user_id": str(jane_id),
            "handle": "jane",
        },
    )
    assert r.status_code in (303, 400)
    assert bob.post("/studio/publish/withdraw", data={"csrf": csrf(bob)}).status_code == 303
    assert bob.post("/studio/publish/search", data={"csrf": csrf(bob), "user_id": str(jane_id)}).status_code == 303
    files = {"file": ("x.txt", b"Bob again", "text/plain")}
    data = {"csrf": csrf(bob), "slot": "document", "user_id": str(jane_id)}
    assert bob.post("/studio/files", data=data, files=files).status_code == 303
    assert file_ids(cloud_settings, "jane") == jane_files
    assert db_rows(cloud_settings, "SELECT data, status FROM personas WHERE user_id = ?", jane_id) == jane_before
    assert db_rows(cloud_settings, "SELECT decided_at FROM reviews WHERE id = ?", rid) == [(None,)]
    assert db_rows(cloud_settings, "SELECT handle FROM users ORDER BY id") == [("jane",), ("bob",)]

    # Delete: retyping Jane's handle deletes nobody.
    r = bob.post("/studio/account/delete", data={"csrf": csrf(bob), "confirm": "jane"})
    assert r.status_code == 400
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM users") == [(2,)]

    # Export: Bob's zip holds Bob's things only.
    with zipfile.ZipFile(io.BytesIO(bob.get("/studio/account/export").content)) as z:
        blob = b"".join(z.read(n) for n in z.namelist())
    assert b"Jane" not in blob
    assert b"jane" not in blob
    assert b"Bob private notes" in blob

    # Jane still has everything.
    assert jane.get(f"/studio/files/{jane_files[0]}").status_code == 200
    assert jane.get("/v1/personas/jane~preview", headers={"origin": PUBLIC_URL}).status_code == 200


def test_the_draft_status_is_per_member(cloud_settings):
    app = app_for(cloud_settings)
    jane, bob = two_members(app, cloud_settings)
    uid = user_id(cloud_settings, "jane")
    db_exec(
        cloud_settings,
        "INSERT INTO audit_log (at, action, user_id) VALUES (?, 'draft.started', ?)",
        int(time.time()),
        uid,
    )
    assert jane.get("/studio/draft/status").json()["state"] == "interrupted"
    assert bob.get("/studio/draft/status").json() == {"state": "none"}


# CSRF and sign-in on every POST


def all_routes(routes):
    """Flatten included routers (FastAPI keeps them nested)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from all_routes(inner.routes)
        else:
            yield route


def sweep(app, settings):
    """Every POST route with real ids filled in, grouped by who may call it."""
    jane_id = user_id(settings, "jane")
    doc_id = file_ids(settings, "jane")[0]
    review = db_rows(settings, "SELECT id FROM reviews WHERE decided_at IS NULL")[0][0]
    pending_request = db_rows(settings, "SELECT id FROM access_requests WHERE status = 'pending'")[0][0]
    member = {
        "/studio/files": ["/studio/files"],
        "/studio/files/{file_id}/delete": [f"/studio/files/{doc_id}/delete"],
        "/studio/text": ["/studio/text"],
        "/studio/draft": ["/studio/draft"],
        "/studio/publish/{action}": [
            f"/studio/publish/{a}" for a in ("submit", "withdraw", "pause", "resume", "search")
        ],
        "/studio/profile": ["/studio/profile"],
        "/studio/account/password": ["/studio/account/password"],
        "/studio/account/delete": ["/studio/account/delete"],
        "/logout": ["/logout"],
    }
    admin = {
        "/admin/logout": ["/admin/logout"],
        "/admin/requests/{request_id}/{action}": [
            f"/admin/requests/{pending_request}/{a}" for a in ("approve", "reject", "delete")
        ],
        "/admin/members/{user_id}/{action}": [
            f"/admin/members/{jane_id}/{a}" for a in ("pause", "unpause", "reset", "delete")
        ],
        "/admin/reviews/{review_id}/{action}": [f"/admin/reviews/{review}/{a}" for a in ("approve", "reject")],
    }
    # Signed-out forms with their own protection (form tokens, origin checks, the honeypot), tested elsewhere.
    public = {"/cloud/requests", "/join/{token}", "/login", "/login/forgot", "/login/reset/{token}", "/admin/login"}
    # The widget's call API: public by design, checked by origin and persona visibility (test_studio_visibility).
    public.add("/v1/personas/{persona_id}/offer")
    posts = {r.path for r in all_routes(app.routes) if "POST" in (getattr(r, "methods", None) or ())}
    assert posts == set(member) | set(admin) | public, "a new POST route needs a line in this sweep"
    return [p for paths in member.values() for p in paths], [p for paths in admin.values() for p in paths]


def snapshot(settings) -> list:
    return [
        db_rows(settings, sql)
        for sql in (
            "SELECT id, status, password_hash FROM users ORDER BY id",
            "SELECT user_id, data, live_data, status, show_in_search FROM personas ORDER BY user_id",
            "SELECT id FROM files ORDER BY id",
            "SELECT id, decided_at FROM reviews ORDER BY id",
            "SELECT sid_hash FROM user_sessions ORDER BY sid_hash",
            "SELECT COUNT(*) FROM password_resets",
            "SELECT id, status FROM access_requests ORDER BY id",
            "SELECT id FROM invites ORDER BY id",
            "SELECT sid FROM revoked_sessions ORDER BY sid",
        )
    ]


def post(client, path, data, headers=None):
    if path == "/studio/files":
        return client.post(path, data=data, files={"file": ("x.txt", b"hello", "text/plain")}, headers=headers)
    return client.post(path, data=data, headers=headers)


@pytest.fixture
def world(cloud_settings):
    app = app_for(cloud_settings)
    jane, bob = two_members(app, cloud_settings)
    request_access(browser(app), email="new@example.com")  # a pending access request
    return app, jane, bob, owner(app)


def test_every_studio_post_needs_a_session_csrf_and_our_origin(world, cloud_settings):
    app, jane, _bob, admin = world
    member_paths, _ = sweep(app, cloud_settings)
    before = snapshot(cloud_settings)
    anon = browser(app)
    form = {"confirm": "jane", "text": "x", "name": "Mallory", "current": PASSWORD, "password": "x" * 20}
    for path in member_paths:
        r = post(anon, path, form)
        assert r.status_code == 303, path
        assert r.headers["location"].startswith("/login"), path
        r = post(admin, path, {**form, "csrf": admin_csrf(admin)})  # the owner's session is not a member's
        assert r.status_code == 303, path
        assert r.headers["location"].startswith("/login"), path
        assert post(jane, path, form).status_code == 403, path
        assert post(jane, path, {**form, "csrf": "forged"}).status_code == 403, path
        assert post(jane, path, {**form, "csrf": csrf(jane)}, headers=EVIL).status_code == 403, path
    assert snapshot(cloud_settings) == before


def test_every_admin_post_needs_the_owner_csrf_and_our_origin(world, cloud_settings):
    app, jane, _bob, admin = world
    _, admin_paths = sweep(app, cloud_settings)
    before = snapshot(cloud_settings)
    anon = browser(app)
    other_admin = owner(app)
    for path in admin_paths:
        assert post(anon, path, {}).headers["location"] == "/admin/login", path
        r = post(jane, path, {"csrf": csrf(jane)})  # a member's session is not the owner's
        assert r.status_code == 303, path
        assert r.headers["location"] == "/admin/login", path
        assert post(admin, path, {}).status_code == 403, path
        assert post(admin, path, {"csrf": "forged"}).status_code == 403, path
        assert post(admin, path, {"csrf": admin_csrf(other_admin)}).status_code == 403, path
        assert post(admin, path, {"csrf": admin_csrf(admin)}, headers=EVIL).status_code == 403, path
    assert snapshot(cloud_settings) == before
    assert re.search(r'name="csrf" value="[^"]+"', admin.get("/admin").text)  # still signed in
