"""Public registration and email-based account recovery."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import APIRouter, HTTPException, Request, Response
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth import (
    COOKIE,
    CurrentUser,
    Session,
    _secret,
    _secure_cookie,
    audit,
    auth_provider,
    limiter,
    passwords,
)
from stock_agents.api.schemas import (
    AuthMessage,
    ChangePasswordRequest,
    EmailRequest,
    EmailTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from stock_agents.common.mail import MailDeliveryError, send_account_email
from stock_agents.storage.postgres import AccountToken, User

router = APIRouter()
REGISTER_MESSAGE = "Check your inbox for a verification link. If you already have an account, sign in or reset your password."
RESET_MESSAGE = "If an account exists for this email, you will receive a password reset link."
VERIFY_MESSAGE = "If your account needs verification, you will receive a new email."


def require_password_provider() -> None:
    if auth_provider() != "jwt":
        raise HTTPException(409, "Manage your account through the configured identity provider")
    _secret()


async def issue_link(session: Session, user: User, purpose: str) -> None:
    """Caller holds the user row lock, serializing resend and token consumption."""
    now = datetime.now(UTC)
    recent = await session.scalar(
        select(AccountToken.token_hash)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.created_at > now - timedelta(seconds=60),
        )
        .limit(1)
    )
    if recent:
        return
    await session.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    token = token_urlsafe(32)
    session.add(
        AccountToken(
            token_hash=sha256(token.encode()).hexdigest(),
            user_id=user.id,
            purpose=purpose,
            expires_at=now + timedelta(minutes=60 if purpose == "verify_email" else 30),
        )
    )
    await session.flush()
    try:
        await run_in_threadpool(send_account_email, user.email, purpose, token)
    except MailDeliveryError as exc:
        await session.rollback()
        raise HTTPException(
            503, "Account email could not be delivered. Please try again later."
        ) from exc


async def consume_link(session: Session, raw_token: str, purpose: str) -> User:
    digest = sha256(raw_token.encode()).hexdigest()
    user_id = await session.scalar(
        select(AccountToken.user_id).where(AccountToken.token_hash == digest)
    )
    if user_id is None:
        raise HTTPException(400, "This link is invalid or expired. Request a new email.")
    # All token operations lock user first, then token, so concurrent resets cannot both win.
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    token = await session.scalar(
        select(AccountToken)
        .where(
            AccountToken.token_hash == digest,
            AccountToken.purpose == purpose,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if user is None or token is None or not user.hashed_pwd:
        raise HTTPException(400, "This link is invalid or expired. Request a new email.")
    token.consumed_at = datetime.now(UTC)
    return user


@router.post("/register", status_code=202, response_model=AuthMessage)
@limiter.limit("5/minute")
async def register(request: Request, response: Response, body: RegisterRequest, session: Session):
    require_password_provider()
    email = body.email.lower()
    existing = await session.scalar(select(User.id).where(func.lower(User.email) == email))
    if existing:
        return AuthMessage(message=REGISTER_MESSAGE)
    user = User(
        email=email,
        hashed_pwd=await run_in_threadpool(passwords.hash, body.password.get_secret_value()),
        is_admin=False,
        email_verified=False,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return AuthMessage(message=REGISTER_MESSAGE)
    await issue_link(session, user, "verify_email")
    audit(session, request, str(user.id), "public_register", {"email": email})
    await session.commit()
    return AuthMessage(message=REGISTER_MESSAGE)


@router.post("/resend-verification", status_code=202, response_model=AuthMessage)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request, response: Response, body: EmailRequest, session: Session
):
    require_password_provider()
    user = await session.scalar(
        select(User).where(func.lower(User.email) == body.email.lower()).with_for_update()
    )
    if user and user.hashed_pwd and not user.email_verified:
        await issue_link(session, user, "verify_email")
        await session.commit()
    return AuthMessage(message=VERIFY_MESSAGE)


@router.post("/verify-email", response_model=AuthMessage)
@limiter.limit("10/minute")
async def verify_email(
    request: Request, response: Response, body: EmailTokenRequest, session: Session
):
    require_password_provider()
    user = await consume_link(session, body.token.get_secret_value(), "verify_email")
    user.email_verified = True
    audit(session, request, str(user.id), "verify_email", {})
    await session.commit()
    return AuthMessage(message="Your email is verified. You can now sign in.")


@router.post("/forgot-password", status_code=202, response_model=AuthMessage)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request, response: Response, body: EmailRequest, session: Session
):
    require_password_provider()
    user = await session.scalar(
        select(User).where(func.lower(User.email) == body.email.lower()).with_for_update()
    )
    if user and user.hashed_pwd:
        await issue_link(session, user, "reset_password")
        await session.commit()
    return AuthMessage(message=RESET_MESSAGE)


async def replace_password(session: Session, request: Request, user: User, password: str) -> None:
    user.hashed_pwd = await run_in_threadpool(passwords.hash, password)
    user.session_version += 1
    user.email_verified = True
    await session.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    audit(session, request, str(user.id), "password_changed", {})
    await session.commit()


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, secure=_secure_cookie(), httponly=True, samesite="strict")


@router.post("/reset-password", response_model=AuthMessage)
@limiter.limit("10/minute")
async def reset_password(
    request: Request, response: Response, body: ResetPasswordRequest, session: Session
):
    require_password_provider()
    user = await consume_link(session, body.token.get_secret_value(), "reset_password")
    await replace_password(session, request, user, body.password.get_secret_value())
    clear_session(response)
    return AuthMessage(message="Password updated. Sign in with your new password.")


@router.post("/change-password", response_model=AuthMessage)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    session: Session,
    actor: CurrentUser,
):
    require_password_provider()
    user = await session.scalar(select(User).where(User.id == actor.id).with_for_update())
    try:
        valid = (
            user
            and user.hashed_pwd
            and await run_in_threadpool(
                passwords.verify,
                body.current_password.get_secret_value(),
                user.hashed_pwd,
            )
        )
    except (UnknownHashError, ValueError):
        valid = False
    if not valid:
        raise HTTPException(400, "Current password is incorrect")
    await replace_password(session, request, user, body.password.get_secret_value())
    clear_session(response)
    return AuthMessage(message="Password updated. Sign in again on each device.")
