"""Password authentication, browser sessions, and admin provisioning."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from json import dumps
from secrets import token_hex
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from stock_agents.api.auth_clerk import verify_clerk_jwt
from stock_agents.api.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from stock_agents.common import config
from stock_agents.storage.postgres import AuditLog, User, get_session

ACCESS_TTL_SECONDS = 3600
COOKIE = "stock_agents_session"
CSRF_HEADER = "X-Stock-Agents-Request"
ISSUER = "stock-agents"
AUDIENCE = "stock-agents-api"
Session = Annotated[AsyncSession, Depends(get_session)]
router = APIRouter()
credentials = HTTPBearer(auto_error=False)
passwords = PasswordHash((Argon2Hasher(), BcryptHasher()))
dummy_hash = passwords.hash(token_hex(32))
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=config.load_settings().env("AUTH_RATE_LIMIT_STORAGE_URL", "memory://"),
    headers_enabled=True,
    key_prefix="stock-agents-auth",
)


def auth_provider() -> str:
    provider = config.load_settings().env("AUTH_PROVIDER", "jwt")
    if provider not in {"jwt", "clerk"}:
        raise HTTPException(503, "Authentication unavailable")
    return provider


def _secret() -> str:
    secret = config.load_settings().env("JWT_SECRET") or ""
    if len(secret.encode()) < 32:
        raise HTTPException(503, "Authentication unavailable")
    return secret


def _secure_cookie() -> bool:
    return config.load_settings().env("AUTH_COOKIE_SECURE", "true").lower() != "false"


def unauthorized() -> HTTPException:
    return HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


def _user_out(user: User) -> UserOut:
    return UserOut(id=str(user.id), email=user.email, is_admin=bool(user.is_admin), email_verified=user.email_verified)


def make_token(user_id: str, session_version: int = 0) -> TokenResponse:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user_id,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=ACCESS_TTL_SECONDS),
            "ver": session_version,
        },
        _secret(),
        algorithm="HS256",
    )
    return TokenResponse(access_token=token, expires_in=ACCESS_TTL_SECONDS)


def _verify_local(token: str) -> tuple[str, int]:
    claims = jwt.decode(
        token,
        _secret(),
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp"]},
    )
    return str(UUID(claims["sub"])), claims.get("ver", 0)


async def _authenticate(
    request: Request, bearer: HTTPAuthorizationCredentials | None, session: AsyncSession
) -> UserOut | None:
    token = bearer.credentials if bearer else request.cookies.get(COOKIE)
    if bearer is None and "authorization" in request.headers:
        raise unauthorized()
    if not token:
        return None
    if bearer is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(403, "Browser request verification failed")
    provider = auth_provider()
    try:
        if provider == "clerk":
            if bearer is None:
                raise unauthorized()
            subject = await run_in_threadpool(verify_clerk_jwt, token)
            query = select(User).where(User.clerk_subject == subject)
        else:
            user_id, version = _verify_local(token)
            query = select(User).where(User.id == user_id, User.session_version == version, User.email_verified.is_(True))
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Identity provider unavailable") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise unauthorized() from exc

    user = await session.scalar(query)
    if user is None:
        raise unauthorized()
    return _user_out(user)


async def get_current_user(
    request: Request, bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(credentials)]
) -> UserOut:
    if bearer is None and COOKIE not in request.cookies:
        raise unauthorized()
    from stock_agents.storage.postgres import session_factory

    async with session_factory()() as session:
        user = await _authenticate(request, bearer, session)
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[UserOut, Depends(get_current_user)]


async def require_market_data_user(
    request: Request, bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(credentials)]
) -> None:
    if config.load_settings().env("REQUIRE_MARKET_DATA_AUTH", "false") == "true":
        await get_current_user(request, bearer)


async def require_admin(request: Request, user: CurrentUser) -> UserOut:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required")
    request.state.user_id = user.id
    return user


AdminUser = Annotated[UserOut, Depends(require_admin)]


def admin_rate_key(request: Request) -> str:
    return request.state.user_id


def audit(session: AsyncSession, request: Request, user_id: str, action: str, fields: dict) -> None:
    canonical = dumps(fields, sort_keys=True, separators=(",", ":"))
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            ip=request.client.host if request.client else None,
            request_hash=sha256(canonical.encode()).hexdigest(),
        )
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, response: Response, body: LoginRequest, session: Session):
    if auth_provider() != "jwt":
        raise HTTPException(409, "Sign in through the configured identity provider")
    _secret()
    password = body.password.get_secret_value()
    if len(password) > 256:
        raise unauthorized()
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()).with_for_update())
    stored_hash = user.hashed_pwd if user and user.hashed_pwd else dummy_hash
    try:
        valid, replacement = await run_in_threadpool(
            passwords.verify_and_update, password, stored_hash
        )
    except (UnknownHashError, ValueError):
        raise unauthorized() from None
    if not user or not user.hashed_pwd or not valid:
        raise unauthorized()
    if not user.email_verified:
        raise HTTPException(403, "Verify your email before signing in. You can request a new verification link.")
    if replacement:
        user.hashed_pwd = replacement
        await session.commit()
    token = make_token(str(user.id), user.session_version)
    response.set_cookie(
        COOKIE,
        token.access_token,
        max_age=token.expires_in,
        httponly=True,
        secure=_secure_cookie(),
        samesite="strict",
    )
    return token


@router.post("/signup", status_code=201, response_model=UserOut)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    response: Response,
    body: SignupRequest,
    session: Session,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(credentials)],
    bootstrap: Annotated[str | None, Header(alias="X-Bootstrap-Signup-Token")] = None,
):
    actor = await _authenticate(request, bearer, session)
    if actor and not actor.is_admin:
        raise HTTPException(403, "Administrator access required")
    if actor is None:
        expected = config.load_settings().env("BOOTSTRAP_SIGNUP_TOKEN") or ""
        if (
            len(expected.encode()) < 32
            or not bootstrap
            or not compare_digest(bootstrap.encode(), expected.encode())
        ):
            raise unauthorized()
        # Serialize first-admin creation and keep a durable record of consumption.
        await session.execute(text("SELECT pg_advisory_xact_lock(490122861)"))
        used = await session.scalar(
            select(
                or_(
                    select(User.id).where(User.is_admin.is_(True)).exists(),
                    select(AuditLog.id).where(AuditLog.action == "bootstrap_signup").exists(),
                )
            )
        )
        if used:
            raise HTTPException(403, "Administrator bootstrap already used")

    if auth_provider() == "jwt":
        _secret()
        password = body.password.get_secret_value() if body.password else ""
        if not 12 <= len(password) <= 256 or body.clerk_subject is not None:
            raise HTTPException(422, "Supply a password between 12 and 256 characters")
        hashed = await run_in_threadpool(passwords.hash, password)
    else:
        if not body.clerk_subject or body.password is not None:
            raise HTTPException(422, "Supply the Clerk user ID")
        hashed = None
    row = User(
        email=body.email.lower(),
        hashed_pwd=hashed,
        clerk_subject=body.clerk_subject,
        is_admin=bool(actor is None or body.is_admin),
    )
    session.add(row)
    try:
        await session.flush()
        audit(
            session,
            request,
            actor.id if actor else str(row.id),
            "signup" if actor else "bootstrap_signup",
            {"email": row.email, "is_admin": row.is_admin, "clerk_subject": row.clerk_subject},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Account already exists") from exc
    return _user_out(row)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request):
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Browser request verification failed")
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, secure=_secure_cookie(), httponly=True, samesite="strict")
    return response
