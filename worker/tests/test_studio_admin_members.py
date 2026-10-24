"""The owner's Members and Reviews tabs: pause, reset links, deletion, approvals, rejections and the audit log."""

import json
import re

import pytest

from openfolio_worker.cloud.admin import AUDIT_LABELS

from cloud_helpers import csrf as admin_csrf
from studio_helpers import (
    PROFILE,
    app_for,
    browser,
    csrf,
    db_rows,
    join,
    mail_app_for,
    make_ready,
    owner,
    save_profile,
    submit,
)


def user_id(settings, handle="jane") -> int:
    return db_rows(settings, "SELECT id FROM users WHERE handle = ?", handle)[0][0]


def open_review(settings) -> int:
    return db_rows(settings, "SELECT id FROM reviews WHERE decided_at IS NULL ORDER BY id DESC")[0][0]


def act(admin, path, **data):
    r = admin.post(path, data={"csrf": admin_csrf(admin), **data})
    assert r.status_code == 303, r.text[-300:]
    return r


def actions(settings) -> list[str]:
    return [a for (a,) in db_rows(settings, "SELECT action FROM audit_log ORDER BY id")]


def go_live(app, settings, handle="jane", **changes):
    member = join(app, settings, handle)
    make_ready(member, **changes)
    assert submit(member).status_code == 303
    admin = owner(app)
    act(admin, f"/admin/reviews/{open_review(settings)}/approve")
    return member, admin


# Members


def test_members_tab_lists_everyone_with_their_page_status(cloud_settings):
    app = app_for(cloud_settings)
    go_live(app, cloud_settings, "jane")
    join(app, cloud_settings, "bob", name="Bob Stone")
    page = owner(app).get("/admin?tab=members")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "@jane" in page.text
    assert "@bob" in page.text
    assert "Bob Stone · bob@example.com" in page.text
    assert 'href="/p/jane"' in page.text  # live
    assert ">Draft<" in page.text  # bob
    assert f'action="/admin/members/{user_id(cloud_settings, "bob")}/pause"' in page.text


def test_pause_takes_the_page_offline_and_signs_the_member_out(cloud_settings):
    app = app_for(cloud_settings)
    jane, admin = go_live(app, cloud_settings)
    stranger = browser(app)
    uid = user_id(cloud_settings)
    assert stranger.get("/p/jane").status_code == 200

    r = act(admin, f"/admin/members/{uid}/pause")
    assert r.headers["location"] == "/admin?tab=members"
    assert db_rows(cloud_settings, "SELECT status FROM users") == [("paused",)]
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM user_sessions WHERE user_id = ?", uid) == [(0,)]
    assert jane.get("/studio/account").status_code == 303
    assert stranger.get("/p/jane").status_code == 404
    assert stranger.get("/p/jane.md").status_code == 404
    assert "jane" not in app.state.cloud.registry.live_ids
    page = admin.get("/admin?tab=members")
    assert "Paused @jane" in page.text
    assert f'action="/admin/members/{uid}/unpause"' in page.text
    assert "Live (account paused)" in page.text

    act(admin, f"/admin/members/{uid}/unpause")
    assert db_rows(cloud_settings, "SELECT status FROM users") == [("active",)]
    assert stranger.get("/p/jane").status_code == 200
    assert "jane" in app.state.cloud.registry.live_ids
    assert jane.get("/studio/account").status_code == 303  # sessions don't come back; they sign in again
    assert "@jane is active again." in admin.get("/admin?tab=members").text
    assert actions(cloud_settings)[-2:] == ["user.paused", "user.unpaused"]
    assert db_rows(cloud_settings, "SELECT user_id FROM audit_log WHERE action = 'user.paused'") == [(uid,)]


def test_reset_link_is_shown_once_and_works(cloud_settings):
    app = app_for(cloud_settings)
    join(app, cloud_settings, "jane")
    admin = owner(app)
    uid = user_id(cloud_settings)
    act(admin, f"/admin/members/{uid}/reset")
    page = admin.get("/admin?tab=members")
    link = re.search(r'id="reset-link"[^>]*value="([^"]+)"', page.text).group(1)
    assert "Send this link to jane@example.com." in page.text
    assert link.startswith("http://127.0.0.1:7872/login/reset/")
    token = link.rsplit("/", 1)[1]
    stored = db_rows(cloud_settings, "SELECT token_hash, user_id FROM password_resets")
    assert len(stored) == 1
    assert stored[0][1] == uid
    assert token not in stored[0][0]
    assert 'id="reset-link"' not in admin.get("/admin?tab=members").text  # a one-time flash
    assert browser(app).get(f"/login/reset/{token}").status_code == 200
    # A second link replaces the first.
    act(admin, f"/admin/members/{uid}/reset")
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM password_resets") == [(1,)]
    assert browser(app).get(f"/login/reset/{token}").status_code == 404
    assert actions(cloud_settings).count("user.reset.issued") == 2


def test_reset_link_is_emailed_when_smtp_is_set(cloud_settings, monkeypatch):
    app, settings, outbox = mail_app_for(cloud_settings, monkeypatch)
    join(app, settings, "jane")
    admin = owner(app)
    act(admin, f"/admin/members/{user_id(settings)}/reset")
    ((to, subject, body),) = outbox.sent
    assert to == "jane@example.com"
    assert "Reset" in subject
    assert "/login/reset/" in body
    assert "It was emailed to jane@example.com." in admin.get("/admin?tab=members").text


def test_owner_delete_erases_the_member(cloud_settings):
    app = app_for(cloud_settings)
    _jane, admin = go_live(app, cloud_settings)
    uid = user_id(cloud_settings)
    act(admin, f"/admin/members/{uid}/delete")
    for table in ("users", "personas", "files", "reviews", "user_sessions", "access_requests", "invites"):
        assert db_rows(cloud_settings, f"SELECT COUNT(*) FROM {table}") == [(0,)], table
    assert not (cloud_settings.data_dir / "users" / str(uid)).exists()
    assert browser(app).get("/p/jane").status_code == 404
    assert app.state.cloud.registry.live_ids == []
    assert "Deleted @jane and all their data." in admin.get("/admin?tab=members").text
    assert db_rows(cloud_settings, "SELECT user_id, detail FROM audit_log WHERE action = 'user.deleted'") == [
        (None, "by the owner")
    ]
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM audit_log WHERE user_id = ?", uid) == [(0,)]


def test_unknown_member_or_action(cloud_settings):
    app = app_for(cloud_settings)
    join(app, cloud_settings, "jane")
    admin = owner(app)
    act(admin, "/admin/members/999/pause")
    assert "That member no longer exists." in admin.get("/admin?tab=members").text
    r = admin.post(f"/admin/members/{user_id(cloud_settings)}/promote", data={"csrf": admin_csrf(admin)})
    assert r.status_code == 404
    assert db_rows(cloud_settings, "SELECT status FROM users") == [("active",)]


# Reviews


def test_reviews_tab_and_preview_page(cloud_settings):
    app = app_for(cloud_settings)
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    admin = owner(app)
    assert "Nothing to review" in admin.get("/admin?tab=reviews").text
    submit(jane)
    rid = open_review(cloud_settings)
    page = admin.get("/admin?tab=reviews")
    assert "@jane" in page.text
    assert f'href="/admin/reviews/{rid}"' in page.text
    assert f'action="/admin/reviews/{rid}/approve"' in page.text
    assert '<span class="count count-hot">1</span>' in page.text
    preview = admin.get(f"/admin/reviews/{rid}")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert "Submission from @jane, not public yet." in preview.text
    assert 'data-persona="jane~preview"' in preview.text
    assert admin.get("/admin/reviews/999").status_code == 404
    assert browser(app).get(f"/admin/reviews/{rid}").headers["location"] == "/admin/login"
    assert jane.get(f"/admin/reviews/{rid}").headers["location"] == "/admin/login"


def test_approve_puts_the_submitted_version_live_and_emails_the_member(cloud_settings, monkeypatch):
    app, settings, outbox = mail_app_for(cloud_settings, monkeypatch)
    jane = join(app, settings, "jane")
    make_ready(jane)
    submit(jane)
    outbox.sent.clear()
    save_profile(jane, title="Edited after submitting")  # not part of the submission
    admin = owner(app)
    rid = open_review(settings)
    act(admin, f"/admin/reviews/{rid}/approve")

    status, live, published = db_rows(settings, "SELECT status, live_data, published_at FROM personas")[0]
    assert status == "live"
    assert json.loads(live)["title"] == PROFILE["title"]
    assert published is not None
    assert db_rows(settings, "SELECT decision FROM reviews WHERE id = ?", rid) == [("approved",)]
    assert app.state.cloud.registry.get("jane").title == PROFILE["title"]
    page = browser(app).get("/p/jane")
    assert page.status_code == 200
    assert "Edited after submitting" not in page.text
    ((to, subject, body),) = outbox.sent
    assert to == "jane@example.com"
    assert subject == "Your Openfolio page is live"
    assert "http://127.0.0.1:7872/p/jane" in body
    assert "@jane is live at /p/jane." in admin.get("/admin?tab=reviews").text
    assert db_rows(settings, "SELECT user_id, detail FROM audit_log WHERE action = 'review.approved'") == [
        (user_id(settings), "emailed")
    ]
    # The member sees the live state and the edit that isn't live yet.
    publish = jane.get("/studio/publish")
    assert "Your page is live" in publish.text
    assert "changes that aren" in publish.text


def test_reject_sends_the_note_back(cloud_settings, monkeypatch):
    app, settings, outbox = mail_app_for(cloud_settings, monkeypatch)
    jane = join(app, settings, "jane")
    make_ready(jane)
    submit(jane)
    outbox.sent.clear()
    admin = owner(app)
    rid = open_review(settings)
    act(admin, f"/admin/reviews/{rid}/reject", note="Please add <b>a real photo</b>.\r\nThanks!")
    assert db_rows(settings, "SELECT status, live_data FROM personas") == [("rejected", None)]
    assert db_rows(settings, "SELECT decision, note FROM reviews") == [
        ("rejected", "Please add <b>a real photo</b>.\nThanks!")
    ]
    assert "jane" not in app.state.cloud.registry.live_ids
    assert browser(app).get("/p/jane").status_code == 404
    ((to, subject, body),) = outbox.sent
    assert to == "jane@example.com"
    assert "changes" in subject
    assert "Please add <b>a real photo</b>." in body  # a plain-text email
    assert "Sent @jane&#39;s page back with your note." in admin.get("/admin?tab=reviews").text
    publish = jane.get("/studio/publish")
    assert "A few changes are needed" in publish.text
    assert "Please add &lt;b&gt;a real photo&lt;/b&gt;." in publish.text  # escaped on the page
    assert "review.rejected" in actions(settings)
    # Submitting again opens a new review.
    assert submit(jane).status_code == 303
    assert db_rows(settings, "SELECT status FROM personas") == [("pending",)]


def test_reviews_are_decided_once(cloud_settings):
    app = app_for(cloud_settings)
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    submit(jane)
    admin = owner(app)
    rid = open_review(cloud_settings)
    act(admin, f"/admin/reviews/{rid}/approve")
    act(admin, f"/admin/reviews/{rid}/reject", note="too late")
    assert "That submission was already decided." in admin.get("/admin?tab=reviews").text
    assert db_rows(cloud_settings, "SELECT status FROM personas") == [("live",)]
    assert db_rows(cloud_settings, "SELECT decision, note FROM reviews") == [("approved", "")]
    r = admin.post(f"/admin/reviews/{rid}/publish", data={"csrf": admin_csrf(admin)})
    assert r.status_code == 404


def test_an_update_to_a_live_page_keeps_the_old_version_until_approved(cloud_settings):
    app = app_for(cloud_settings)
    jane, admin = go_live(app, cloud_settings)
    stranger = browser(app)
    save_profile(jane, title="Principal Product Designer")
    submit(jane)
    assert db_rows(cloud_settings, "SELECT status FROM personas") == [("live",)]
    assert "Senior Product Designer" in stranger.get("/p/jane").text
    assert "update to a live page" in admin.get("/admin?tab=reviews").text
    act(admin, f"/admin/reviews/{open_review(cloud_settings)}/approve")
    assert "Principal Product Designer" in stranger.get("/p/jane").text
    assert app.state.cloud.registry.get("jane").title == "Principal Product Designer"


def test_approving_while_the_member_paused_keeps_the_page_paused(cloud_settings):
    app = app_for(cloud_settings)
    jane, admin = go_live(app, cloud_settings)
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    save_profile(jane, title="Principal Product Designer")
    submit(jane)
    act(admin, f"/admin/reviews/{open_review(cloud_settings)}/approve")
    assert db_rows(cloud_settings, "SELECT status FROM personas") == [("paused",)]
    assert browser(app).get("/p/jane").status_code == 404
    jane.post("/studio/publish/resume", data={"csrf": csrf(jane)})
    assert "Principal Product Designer" in browser(app).get("/p/jane").text


# Audit log


def test_every_step_is_audited_without_personal_data(cloud_settings):
    app = app_for(cloud_settings)
    jane, admin = go_live(app, cloud_settings)
    uid = user_id(cloud_settings)
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    jane.post("/studio/publish/resume", data={"csrf": csrf(jane)})
    jane.get("/studio/account/export")
    act(admin, f"/admin/members/{uid}/reset")
    logged = actions(cloud_settings)
    for event in (
        "login",
        "user.created",
        "file.uploaded",
        "persona.saved",
        "persona.submitted",
        "review.approved",
        "persona.paused",
        "persona.resumed",
        "data.exported",
        "user.reset.issued",
    ):
        assert event in logged, event
    assert set(logged) <= set(AUDIT_LABELS), set(logged) - set(AUDIT_LABELS)
    for (detail,) in db_rows(cloud_settings, "SELECT detail FROM audit_log"):
        assert "@" not in detail
        assert "Jane" not in detail
    page = admin.get("/admin?tab=members")
    for label in ("Page approved", "Page paused", "Data exported", "Reset link issued"):
        assert label in page.text
    assert f"member #{uid}" in page.text


@pytest.mark.parametrize("event", sorted(AUDIT_LABELS))
def test_audit_labels_are_short(event):
    assert 0 < len(AUDIT_LABELS[event]) <= 30
