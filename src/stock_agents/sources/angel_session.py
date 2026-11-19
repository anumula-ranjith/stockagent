"""Short-lived encrypted broker session; PIN and one-time codes are never persisted."""
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet, InvalidToken

from stock_agents.common.config import load_settings
from stock_agents.jobs.queue import _redis, redis_url
from stock_agents.sources.angel_one import BASE, LOGIN, AngelOneError, _data, smartapi_headers

KEY = "quantora:angel-market-session"
TZ = ZoneInfo("Asia/Kolkata")


def cipher():
    secret = load_settings().env("JWT_SECRET") or ""
    if len(secret) < 32:
        raise AngelOneError("Server session encryption is not configured")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("angel-market-session:"+secret).encode()).digest()))


def read_session():
    value = _redis(redis_url()).get(KEY)
    if not value:
        return None
    try:
        data = json.loads(cipher().decrypt(value))
        if datetime.fromisoformat(data["expires_at"]) > datetime.now(UTC):
            return data
    except (InvalidToken, ValueError, KeyError):
        pass
    return None


def connection_status():
    settings = load_settings()
    data = read_session()
    return {"connected": bool(data), "stream_ready":bool(data and data.get("feed_token") and data.get("client_code")), "expires_at":data["expires_at"] if data else None,
        "configured":all(settings.env("ANGEL_ONE_"+n) for n in ("API_KEY","CLIENT_CODE","PIN")),
        "account_mask":data["account_mask"] if data else None}


def connect_code(code: str):
    settings = load_settings()
    credentials = {n:(settings.env("ANGEL_ONE_"+n) or "").strip() for n in ("API_KEY","CLIENT_CODE","PIN")}
    if not all(credentials.values()):
        raise AngelOneError("Configure the Angel One API key, client code and PIN on the server first")
    with httpx.Client(base_url=BASE, headers=smartapi_headers(credentials["API_KEY"]), timeout=12, follow_redirects=False) as client:
        try:
            data = _data(client.post(LOGIN,json={"clientcode":credentials["CLIENT_CODE"],"password":credentials["PIN"],"totp":code}),"login")
        except httpx.HTTPError:
            raise AngelOneError("Angel One login is unavailable; try a fresh code") from None
    token = data.get("jwtToken") if isinstance(data,dict) else None
    if not isinstance(token,str) or not token:
        raise AngelOneError("Angel One did not return a session")
    now = datetime.now(TZ)
    expires = (now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    session = {"feed_token":data.get("feedToken"),"client_code":credentials["CLIENT_CODE"],"token":token,"api_key":credentials["API_KEY"],"account_mask":"••••"+credentials["CLIENT_CODE"][-4:],"expires_at":expires.isoformat()}
    _redis(redis_url()).set(KEY,cipher().encrypt(json.dumps(session).encode()),ex=max(1,int((expires-now).total_seconds())))
    return connection_status()
