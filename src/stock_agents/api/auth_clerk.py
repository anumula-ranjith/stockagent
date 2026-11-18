"""Validate Clerk session tokens against the configured issuer and JWKS."""

from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException

from stock_agents.common import config


@lru_cache(maxsize=8)
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, lifespan=600, timeout=5)


def verify_clerk_jwt(token: str) -> str:
    settings = config.load_settings()
    issuer = settings.env("CLERK_ISSUER") or ""
    url = settings.env("CLERK_JWKS_URL") or ""
    origins = (settings.env("CLERK_AUTHORIZED_PARTIES") or "").split(",")
    allowed = {origin.strip() for origin in origins if origin.strip()}
    if (
        urlsplit(issuer).scheme != "https"
        or not urlsplit(issuer).hostname
        or urlsplit(url).scheme != "https"
        or not urlsplit(url).hostname
        or not allowed
    ):
        raise HTTPException(503, "Identity provider unavailable")

    audience = settings.env("CLERK_AUDIENCE") or None
    if jwt.get_unverified_header(token).get("alg") != "RS256":
        raise jwt.InvalidAlgorithmError("Unexpected Clerk algorithm")
    key = _jwks(url).get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=audience,
        options={
            "require": ["exp", "iat", "iss", "nbf", "sub", "azp"],
            "verify_aud": audience is not None,
        },
    )
    if (
        not isinstance(claims["azp"], str)
        or claims["azp"] not in allowed
        or claims.get("sts") == "pending"
        or not 1 <= len(claims["sub"]) <= 255
    ):
        raise jwt.InvalidTokenError("Invalid Clerk session")
    return claims["sub"]
