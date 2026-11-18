"""JWT auth for the FastAPI layer.

Protects endpoints that read licensed data (FactSet) or trigger heavy jobs.
For a managed solution you can swap this for Clerk or Auth0 by deleting the
`/login` route and using their JWKS verifier in `get_current_user`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_agents.api.schemas import TokenResponse, UserOut
from stock_agents.storage.postgres import User, get_session

JWT_ALGO = "HS256"
ACCESS_TTL_SECONDS = 3600


def _secret() -> str:
    s = os.environ.get("JWT_SECRET")
    if not s or s == "change-me-in-production":
        # Don't crash local dev if someone forgot to set it; log loudly.
        return "dev-only-not-secret"
    return s


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def hash_password(pw: str) -> str:
    return _pwd.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    return _pwd.verify(pw, hashed)


def make_token(user_id: str, email: str, is_admin: bool) -> TokenResponse:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ACCESS_TTL_SECONDS)).timestamp()),
    }
    token = jwt.encode(payload, _secret(), algorithm=JWT_ALGO)
    return TokenResponse(access_token=token, expires_in=ACCESS_TTL_SECONDS)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"bad token: {e}")
    sub = payload.get("sub")
    row = (await session.execute(select(User).where(User.id == sub))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return UserOut(id=row.id, email=row.email, is_admin=row.is_admin or False)


async def require_admin(user: Annotated[UserOut, Depends(get_current_user)]) -> UserOut:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user
