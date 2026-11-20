"""Private, read-only Angel One snapshot flow."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select

from stock_agents.api.auth import CurrentUser, Session, limiter
from stock_agents.sources.angel_one import AngelOneError, fetch_snapshot
from stock_agents.storage.postgres import BrokerSnapshot, User

router = APIRouter(prefix="/brokers/angel-one", tags=["broker"])


class SyncInput(BaseModel):
    api_key: SecretStr = Field(min_length=4, max_length=200)
    client_code: str = Field(min_length=3, max_length=30)
    password: SecretStr = Field(min_length=4, max_length=100)
    totp: str = Field(pattern=r"^\d{6}$")


class SnapshotOut(BaseModel):
    broker: str
    account_mask: str
    fetched_at: datetime
    holdings: list[dict]
    trades: list[dict]


def output(row: BrokerSnapshot) -> SnapshotOut:
    return SnapshotOut(broker=row.broker, account_mask=row.account_mask,
        fetched_at=row.fetched_at, holdings=row.holdings, trades=row.trades)


@router.get("/snapshot", response_model=SnapshotOut | None)
async def snapshot(user: CurrentUser, session: Session):
    row = await session.get(BrokerSnapshot, (user.id, "angel_one"))
    return output(row) if row else None


@router.post("/sync", response_model=SnapshotOut)
@limiter.limit("2/minute")
async def sync(request: Request, response: Response, body: SyncInput, user: CurrentUser, session: Session):
    try:
        holdings, trades = await fetch_snapshot(body.api_key.get_secret_value(), body.client_code.strip().upper(),
            body.password.get_secret_value(), body.totp)
    except AngelOneError as exc:
        raise HTTPException(502, str(exc)) from exc
    await session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    row = await session.get(BrokerSnapshot, (user.id, "angel_one"))
    if row is None:
        row = BrokerSnapshot(user_id=user.id, broker="angel_one")
        session.add(row)
    row.account_mask = "••••" + body.client_code.strip().upper()[-4:]
    row.holdings = holdings
    row.trades = trades
    row.fetched_at = datetime.now(UTC)
    await session.commit()
    return output(row)


@router.delete("/snapshot", status_code=204)
async def delete_snapshot(user: CurrentUser, session: Session):
    row = await session.get(BrokerSnapshot, (user.id, "angel_one"))
    if row:
        await session.delete(row)
        await session.commit()
