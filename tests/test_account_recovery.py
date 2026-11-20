from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from stock_agents.api import auth
from stock_agents.api.main import app
from stock_agents.storage.postgres import User

EMAIL = "member@example.com"
PASSWORD = "a long original password"
NEW_PASSWORD = "a different secure password"


@pytest.fixture
def account_client(auth_database, monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "jwt")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("JWT_SECRET", "test-recovery-signing-secret-with-at-least-32-bytes")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3001")
    from stock_agents.api import account

    sent = []
    monkeypatch.setattr(account, "send_account_email", lambda *args: sent.append(args))
    auth.limiter.reset()
    with TestClient(app) as client:
        yield client, sent, auth_database


def test_signup_verify_reset_change_password_and_revoke_sessions(account_client):
    client, sent, engine = account_client
    fields = {"email": EMAIL, "password": PASSWORD, "is_admin": True}
    # Privilege fields cannot enter the public registration contract.
    assert client.post("/register", json=fields).status_code == 422
    fields.pop("is_admin")
    result = client.post("/register", json=fields)
    assert result.status_code == 202, result.text
    assert len(sent) == 1
    verification_token = sent[-1][2]
    with engine.connect() as connection:
        user = connection.execute(select(User.__table__)).one()
        assert not user.is_admin and not user.email_verified
    assert client.post("/login", json=fields).status_code == 403
    assert (
        client.post(
            "/reset-password", json={"token": verification_token, "password": NEW_PASSWORD}
        ).status_code
        == 400
    )
    assert client.post("/verify-email", json={"token": verification_token}).status_code == 200
    assert client.post("/verify-email", json={"token": verification_token}).status_code == 400
    login = client.post("/login", json=fields)
    assert login.status_code == 200
    old_session = login.json()["access_token"]
    assert client.get("/me").json()["email_verified"]

    known = client.post("/forgot-password", json={"email": EMAIL})
    unknown = client.post("/forgot-password", json={"email": "unknown@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    reset_token = sent[-1][2]
    from stock_agents.storage.postgres import AccountToken

    with engine.connect() as connection:
        hashes = connection.execute(select(AccountToken.token_hash)).scalars().all()
        assert reset_token not in hashes and sha256(reset_token.encode()).hexdigest() in hashes
    assert (
        client.post("/reset-password", json={"token": reset_token, "password": "short"}).status_code
        == 422
    )
    assert (
        client.post(
            "/reset-password", json={"token": reset_token, "password": NEW_PASSWORD}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/reset-password", json={"token": reset_token, "password": NEW_PASSWORD}
        ).status_code
        == 400
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {old_session}"}).status_code == 401
    auth.limiter.reset()
    assert client.post("/login", json=fields).status_code == 401
    login = client.post("/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert login.status_code == 200
    token = login.json()["access_token"]
    body = {"current_password": NEW_PASSWORD, "password": PASSWORD}
    assert client.post("/change-password", json=body).status_code == 403
    headers = {"X-Stock-Agents-Request": "1"}
    assert (
        client.post(
            "/change-password", json={**body, "current_password": "wrong"}, headers=headers
        ).status_code
        == 400
    )
    assert client.post("/change-password", json=body, headers=headers).status_code == 200
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_expired_link_duplicate_signup_and_resend(account_client):
    from stock_agents.storage.postgres import AccountToken

    client, sent, engine = account_client
    fields = {"email": EMAIL, "password": PASSWORD}
    first = client.post("/register", json=fields)
    duplicate = client.post("/register", json={**fields, "password": NEW_PASSWORD})
    assert first.status_code == duplicate.status_code == 202
    assert first.json() == duplicate.json()
    assert len(sent) == 1
    with engine.begin() as connection:
        connection.execute(
            update(AccountToken).values(
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                created_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
    assert client.post("/verify-email", json={"token": sent[0][2]}).status_code == 400
    assert client.post("/resend-verification", json={"email": EMAIL}).status_code == 202
    assert len(sent) == 2
    assert client.post("/verify-email", json={"token": sent[-1][2]}).status_code == 200
    assert client.post("/login", json=fields).status_code == 200


def test_mail_failure_rolls_back_new_registration(account_client, monkeypatch):
    from stock_agents.api import account
    from stock_agents.common.mail import MailDeliveryError

    client, _, engine = account_client

    def fail(*args):
        raise MailDeliveryError("Mail delivery is temporarily unavailable")

    monkeypatch.setattr(account, "send_account_email", fail)
    response = client.post("/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 503
    with engine.connect() as connection:
        assert connection.execute(select(User.id)).first() is None


def test_concurrent_reset_consumes_token_once(account_client):
    client, sent, _ = account_client
    assert client.post("/register", json={"email": EMAIL, "password": PASSWORD}).status_code == 202
    assert client.post("/forgot-password", json={"email": EMAIL}).status_code == 202
    body = {"token": sent[-1][2], "password": NEW_PASSWORD}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post("/reset-password", json=body).status_code, range(2))
        )
    assert sorted(results) == [200, 400]


def test_smtp_uses_tls_and_fragment_link(monkeypatch):
    from stock_agents.common import mail

    monkeypatch.setenv("EMAIL_HOST", "smtp.gmail.com")
    monkeypatch.setenv("EMAIL", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "test app password")
    monkeypatch.setenv("EMAIL_PORT", "587")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3001")
    events = []

    class SMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.gmail.com", 587)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            pass

        def starttls(self, context):
            events.append("tls")

        def login(self, email, password):
            assert events == ["tls"]
            assert (email, password) == ("sender@example.com", "testapppassword")
            events.append("login")

        def send_message(self, message):
            assert events == ["tls", "login"]
            assert message["To"] == EMAIL
            assert "http://localhost:3001/reset-password#token=test-token" in message.get_content()
            events.append("sent")

    monkeypatch.setattr(mail.smtplib, "SMTP", SMTP)
    mail.send_account_email(EMAIL, "reset_password", "test-token")
    assert events[-1] == "sent"
