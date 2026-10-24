import smtplib
from dataclasses import replace
from typing import ClassVar

import pytest

from openfolio_worker.cloud.mail import build_message, clean_header
from openfolio_worker.config import SmtpSettings

from cloud_helpers import approve, client_for, login, rows, submit
from conftest import PUBLIC_URL

SMTP = SmtpSettings(
    host="smtp.example.com",
    port=587,
    sender="owner@example.com",
    user="owner@example.com",
    password="app-password",
    notify_email="owner@example.com",
)


class FakeSMTP:
    sent: ClassVar[list] = []
    events: ClassVar[list] = []
    fail = False

    def __init__(self, host, port, timeout=None):
        FakeSMTP.events.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.events.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.events.append(("login", user))

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise smtplib.SMTPServerDisconnected("gone")
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.events, FakeSMTP.fail = [], [], False
    monkeypatch.setattr("openfolio_worker.cloud.mail.smtplib.SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def mail_settings(cloud_settings):
    return replace(cloud_settings, cloud=replace(cloud_settings.cloud, smtp=SMTP))


def test_header_injection_is_stripped():
    msg = build_message(
        "owner@example.com\r\nBcc: a@evil.example",
        "x@example.com\nCc: b@evil.example",
        "Hello\r\nBcc: c@evil.example",
        "body",
    )
    assert msg["Bcc"] is None
    assert msg["Cc"] is None
    for header in ("From", "To", "Subject"):
        assert "\n" not in msg[header]
        assert "\r" not in msg[header]
    assert "\nBcc:" not in msg.as_string()
    assert clean_header("a\u2028b") == "a b"


def test_new_request_notifies_the_owner(mail_settings, smtp):
    r = submit(client_for(mail_settings), name="Eve Example")
    assert r.status_code == 303
    (msg,) = smtp.sent
    assert msg["To"] == "owner@example.com"
    assert msg["Subject"] == "Openfolio Cloud: access request from Eve Example"
    body = msg.get_content()
    assert f"{PUBLIC_URL}/admin" in body
    assert "jane@example.com" in body
    assert msg.get_content_type() == "text/plain"
    assert ("starttls",) in smtp.events
    assert ("login", "owner@example.com") in smtp.events


def test_approval_emails_the_invite(mail_settings, smtp):
    client = client_for(mail_settings)
    submit(client)
    login(client)
    token = approve(client, mail_settings)
    invite = smtp.sent[-1]
    assert invite["To"] == "jane@example.com"
    assert f"{PUBLIC_URL}/invite/{token}" in invite.get_content()
    assert ("invite emailed",) in rows(mail_settings, "SELECT detail FROM audit_log WHERE action = 'request.approved'")


def test_email_failure_never_breaks_a_request(mail_settings, smtp):
    smtp.fail = True
    client = client_for(mail_settings)
    assert submit(client).status_code == 303
    assert rows(mail_settings, "SELECT COUNT(*) FROM access_requests") == [(1,)]
    login(client)
    token = approve(client, mail_settings)  # the link is still shown once
    assert token
    page_detail = rows(mail_settings, "SELECT detail FROM audit_log WHERE action = 'request.approved'")
    assert page_detail == [("invite email failed",)]


def test_failed_email_is_explained_on_the_admin_page(mail_settings, smtp):
    smtp.fail = True
    client = client_for(mail_settings)
    submit(client)
    login(client)
    from cloud_helpers import csrf, request_id

    r = client.post(f"/admin/requests/{request_id(mail_settings)}/approve", data={"csrf": csrf(client)})
    assert "failed. Send this link yourself" in client.get(r.headers["location"]).text


def test_without_smtp_nothing_is_sent(cloud_settings, smtp):
    client = client_for(cloud_settings)
    submit(client)
    login(client)
    approve(client, cloud_settings)
    assert smtp.sent == []
    assert smtp.events == []
