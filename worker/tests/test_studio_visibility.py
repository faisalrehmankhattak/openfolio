"""Who can see and call a member's persona: drafts, submissions, live pages, pauses and deletion."""

import json
import re

from openfolio_worker.cloud import profiles

from cloud_helpers import csrf as admin_csrf
from conftest import PUBLIC_URL
from studio_helpers import (
    app_for,
    browser,
    csrf,
    db_rows,
    join,
    make_ready,
    owner,
    submit,
)

SAME_ORIGIN = {"origin": PUBLIC_URL}
OFFER = {"sdp": "v=0", "type": "offer"}


def review_id(settings) -> int:
    return db_rows(settings, "SELECT id FROM reviews WHERE decided_at IS NULL ORDER BY id DESC")[0][0]


def approve(admin, settings):
    r = admin.post(f"/admin/reviews/{review_id(settings)}/approve", data={"csrf": admin_csrf(admin)})
    assert r.status_code == 303


def go_live(app, settings, handle="jane", **changes):
    member = join(app, settings, handle)
    make_ready(member, **changes)
    assert submit(member).status_code == 303
    admin = owner(app)
    approve(admin, settings)
    return member, admin


def callable_by(client, handle, headers=None) -> list[int]:
    """Status codes of the three calls a visitor's widget makes."""
    headers = headers or SAME_ORIGIN
    return [
        client.get(f"/v1/personas/{handle}", headers=headers).status_code,
        client.get(f"/v1/personas/{handle}/ice-servers", headers=headers).status_code,
        client.post(f"/v1/personas/{handle}/offer", json=OFFER, headers=headers).status_code,
    ]


def test_drafts_and_submissions_are_not_callable_by_anyone_else(cloud_settings):
    app = app_for(cloud_settings)
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    stranger, bob = browser(app), join(app, cloud_settings, "bob")
    for client in (stranger, bob, jane):
        assert callable_by(client, "jane") == [404, 404, 404]  # the published id: nothing is live
    for client in (stranger, bob):
        assert callable_by(client, "jane~preview") == [404, 404, 404]
    assert submit(jane).status_code == 303
    for client in (stranger, bob):
        assert callable_by(client, "jane") == [404, 404, 404]
        assert callable_by(client, "jane~preview") == [404, 404, 404]
    assert "jane" not in app.state.cloud.registry.live_ids


def test_the_owner_previews_only_on_public_url_with_their_session(cloud_settings):
    app = app_for(cloud_settings)
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    r = jane.get("/v1/personas/jane~preview", headers=SAME_ORIGIN)
    assert r.status_code == 200
    assert r.json()["name"] == "Jane Doe"
    assert r.headers["cache-control"] == "private, no-store"
    assert jane.get("/v1/personas/jane~preview").status_code == 200  # same-origin GETs may omit Origin
    assert jane.get("/v1/personas/jane~preview/ice-servers", headers=SAME_ORIGIN).status_code == 200
    # Another site, or a cross-site fetch, never gets the draft, even with the member's cookie.
    assert jane.get("/v1/personas/jane~preview", headers={"origin": "https://evil.example"}).status_code == 404
    assert jane.get("/v1/personas/jane~preview", headers={"sec-fetch-site": "cross-site"}).status_code == 404
    assert jane.get("/v1/personas/jane~preview", headers={"origin": "http://127.0.0.1:9999"}).status_code == 404
    # A different member's preview id is just unknown.
    bob = join(app, cloud_settings, "bob")
    assert bob.get("/v1/personas/jane~preview", headers=SAME_ORIGIN).status_code == 404
    # The site owner sees the frozen submission, not later edits.
    assert submit(jane).status_code == 303
    r = jane.post("/studio/profile", data={**_profile(), "title": "Edited after submitting", "csrf": csrf(jane)})
    assert r.status_code == 303
    admin = owner(app)
    assert admin.get("/v1/personas/jane~preview", headers=SAME_ORIGIN).json()["title"] == "Senior Product Designer"
    assert jane.get("/v1/personas/jane~preview", headers=SAME_ORIGIN).json()["title"] == "Edited after submitting"


def _profile():
    from studio_helpers import PROFILE

    return PROFILE


def test_live_personas_are_callable_until_paused_or_deleted(cloud_settings):
    app = app_for(cloud_settings)
    jane, admin = go_live(app, cloud_settings)
    stranger = browser(app)
    r = stranger.get("/v1/personas/jane", headers=SAME_ORIGIN)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=15"  # short, so a pause shows quickly
    assert stranger.get("/v1/personas/jane/ice-servers", headers=SAME_ORIGIN).status_code == 200
    assert "jane" in app.state.cloud.registry.live_ids
    # Embedding on another site is refused even when live (custom domains come later).
    assert stranger.get("/v1/personas/jane/ice-servers", headers={"origin": "https://evil.example"}).status_code == 403

    assert jane.post("/studio/publish/pause", data={"csrf": csrf(jane)}).status_code == 303
    assert callable_by(stranger, "jane") == [404, 404, 404]
    assert jane.post("/studio/publish/resume", data={"csrf": csrf(jane)}).status_code == 303
    assert stranger.get("/v1/personas/jane", headers=SAME_ORIGIN).status_code == 200

    (user_id,) = db_rows(cloud_settings, "SELECT id FROM users WHERE handle = 'jane'")[0]
    assert admin.post(f"/admin/members/{user_id}/pause", data={"csrf": admin_csrf(admin)}).status_code == 303
    assert callable_by(stranger, "jane") == [404, 404, 404]
    assert admin.post(f"/admin/members/{user_id}/unpause", data={"csrf": admin_csrf(admin)}).status_code == 303
    assert stranger.get("/v1/personas/jane", headers=SAME_ORIGIN).status_code == 200
    assert admin.post(f"/admin/members/{user_id}/delete", data={"csrf": admin_csrf(admin)}).status_code == 303
    assert callable_by(stranger, "jane") == [404, 404, 404]
    assert app.state.cloud.registry.live_ids == []


def test_members_cannot_shadow_file_personas(cloud_settings):
    app = app_for(cloud_settings)
    registry = app.state.cloud.registry
    registry.replace_live({"demo": registry.files["demo"].model_copy(update={"name": "Impostor"})})
    assert browser(app).get("/v1/personas/demo").json()["name"] != "Impostor"


# The public page


def ld_json(html: str) -> dict:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    assert match, "no JSON-LD"
    return json.loads(match.group(1))


NASTY = 'Jane </script><script>alert("x")</script> O\'Neil'


def test_profile_page_json_ld_stays_inert(cloud_settings):
    app = app_for(cloud_settings)
    go_live(app, cloud_settings, name=NASTY)
    r = browser(app).get("/p/jane")
    assert r.status_code == 200
    assert "<script>alert" not in r.text
    assert '<script>alert("x")' not in r.text
    ld = ld_json(r.text)
    assert ld["@type"] == "ProfilePage"
    assert ld["mainEntity"]["name"] == NASTY
    assert ld["mainEntity"]["jobTitle"] == "Senior Product Designer"
    assert ld["mainEntity"]["worksFor"] == {"@type": "Organization", "name": "Acme"}
    assert ld["mainEntity"]["sameAs"] == ["https://linkedin.com/in/janedoe"]
    assert ld["mainEntity"]["image"].startswith(f"{PUBLIC_URL}/p/jane/photo-")
    assert "&lt;/script&gt;" in r.text.split("<title>")[1].split("</title>")[0]
    assert f'<link rel="canonical" href="{PUBLIC_URL}/p/jane">' in r.text
    assert "script-src 'self';" in r.headers["content-security-policy"]


def test_markdown_twin(cloud_settings):
    app = app_for(cloud_settings)
    go_live(app, cloud_settings)
    r = browser(app).get("/p/jane.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    text = r.text
    assert text.startswith("# Jane Doe\n")
    for part in (
        "## Experience",
        "**Senior Product Designer**, Acme",
        "Conversion up 18%",
        "<https://linkedin.com/in/janedoe>",
    ):
        assert part in text
    assert f"<{PUBLIC_URL}/p/jane>" in text
    assert "x-robots-tag" not in r.headers


def test_noindex_and_sitemap_follow_show_in_search(cloud_settings):
    app = app_for(cloud_settings)
    jane, _ = go_live(app, cloud_settings)
    stranger = browser(app)
    page = stranger.get("/p/jane")
    assert "x-robots-tag" not in page.headers
    assert 'name="robots" content="noindex"' not in page.text
    assert profiles.public_profile_urls() == [f"{PUBLIC_URL}/p/jane"]

    assert jane.post("/studio/publish/search", data={"csrf": csrf(jane)}).status_code == 303
    page = stranger.get("/p/jane")
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex"
    assert 'name="robots" content="noindex"' in page.text
    assert stranger.get("/p/jane.md").headers["x-robots-tag"] == "noindex"
    assert profiles.public_profile_urls() == []

    assert jane.post("/studio/publish/search", data={"csrf": csrf(jane), "show_in_search": "on"}).status_code == 303
    assert profiles.public_profile_urls() == [f"{PUBLIC_URL}/p/jane"]
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    assert profiles.public_profile_urls() == []


def test_photo_is_public_only_while_live(cloud_settings):
    app = app_for(cloud_settings)
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    (photo_id,) = db_rows(cloud_settings, "SELECT id FROM files WHERE kind = 'photo'")[0]
    url = f"/p/jane/photo-{photo_id}.jpg"
    stranger, admin, bob = browser(app), owner(app), join(app, cloud_settings, "bob")
    assert stranger.get(url).status_code == 404
    assert bob.get(url).status_code == 404
    mine = jane.get(url)
    assert mine.status_code == 200
    assert mine.headers["cache-control"] == "private, no-store"
    assert admin.get(url).status_code == 200
    assert submit(jane).status_code == 303
    approve(admin, cloud_settings)
    public = stranger.get(url)
    assert public.status_code == 200
    assert public.headers["content-type"] == "image/jpeg"
    assert public.headers["cache-control"] == "public, no-cache"
    tag = public.headers["etag"]
    assert stranger.get(url, headers={"if-none-match": tag}).status_code == 304
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    assert stranger.get(url).status_code == 404
    assert stranger.get(url, headers={"if-none-match": tag}).status_code == 404
    assert stranger.get(f"/p/jane/photo-{photo_id + 1}.jpg").status_code == 404
    assert stranger.get("/p/jane/../../etc/passwd").status_code == 404


def test_unknown_draft_pending_rejected_and_paused_pages_are_404(cloud_settings):
    app = app_for(cloud_settings)
    stranger = browser(app)

    def gone(handle):
        for path in (f"/p/{handle}", f"/p/{handle}.md"):
            r = stranger.get(path, headers={"accept": "text/html"})
            assert r.status_code == 404, path
            assert r.headers["cache-control"] == "no-store"
            assert "isn&#39;t public" in r.text or path.endswith(".md")

    gone("nobody")
    gone("Not_A_Handle")
    jane = join(app, cloud_settings, "jane")
    make_ready(jane)
    gone("jane")  # draft
    submit(jane)
    gone("jane")  # pending
    admin = owner(app)
    r = admin.post(f"/admin/reviews/{review_id(cloud_settings)}/reject", data={"csrf": admin_csrf(admin), "note": "x"})
    assert r.status_code == 303
    gone("jane")  # rejected, never live
    submit(jane)
    approve(admin, cloud_settings)
    assert stranger.get("/p/jane").status_code == 200
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    gone("jane")  # paused by the member


def test_public_pages_revalidate_so_a_pause_takes_effect_at_once(cloud_settings):
    app = app_for(cloud_settings)
    jane, _ = go_live(app, cloud_settings)
    stranger = browser(app)
    first = stranger.get("/p/jane")
    assert first.headers["cache-control"] == "public, no-cache"
    tag = first.headers["etag"]
    again = stranger.get("/p/jane", headers={"if-none-match": tag})
    assert again.status_code == 304
    assert again.headers["etag"] == tag
    assert again.content == b""
    jane.post("/studio/publish/pause", data={"csrf": csrf(jane)})
    after = stranger.get("/p/jane", headers={"if-none-match": tag})
    assert after.status_code == 404
    assert after.headers["cache-control"] == "no-store"


def test_owner_pause_and_deletion_take_effect_at_once_on_cached_pages(cloud_settings):
    app = app_for(cloud_settings)
    _jane, admin = go_live(app, cloud_settings)
    stranger = browser(app)
    tags = {path: stranger.get(path).headers["etag"] for path in ("/p/jane", "/p/jane.md")}
    for path, tag in tags.items():
        cached = stranger.get(path, headers={"if-none-match": tag})
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == "public, no-cache"
    (user_id,) = db_rows(cloud_settings, "SELECT id FROM users WHERE handle = 'jane'")[0]

    def offline():
        for path, tag in tags.items():
            r = stranger.get(path, headers={"if-none-match": tag})
            assert r.status_code == 404, path
            assert r.headers["cache-control"] == "no-store"

    assert admin.post(f"/admin/members/{user_id}/pause", data={"csrf": admin_csrf(admin)}).status_code == 303
    offline()
    assert admin.post(f"/admin/members/{user_id}/unpause", data={"csrf": admin_csrf(admin)}).status_code == 303
    assert stranger.get("/p/jane", headers={"if-none-match": tags["/p/jane"]}).status_code == 304
    assert admin.post(f"/admin/members/{user_id}/delete", data={"csrf": admin_csrf(admin)}).status_code == 303
    offline()
