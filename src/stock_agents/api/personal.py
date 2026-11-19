"""Private manual portfolios and watchlists, priced from local EOD observations."""

from datetime import date, datetime
from decimal import Decimal
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from stock_agents.api.auth import CurrentUser, Session
from stock_agents.engine.portfolio_ledger import LedgerError, calculate
from stock_agents.storage.postgres import (
    PortfolioAccount,
    PortfolioEntry,
    Symbology,
    Watchlist,
    WatchlistItem,
)

router = APIRouter(tags=["personal"])
Money = Decimal
_quote_cache: dict[str, tuple[float, "QuoteOut"]] = {}


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PortfolioInput(NameInput):
    initial_cash: Money = Field(default=Decimal(0), ge=0, le=Decimal("1000000000000"))
    initial_date: date | None = None


class EntryInput(BaseModel):
    kind: Literal["deposit", "withdrawal", "buy", "sell"]
    trade_date: date
    ticker: str | None = Field(default=None, max_length=40)
    quantity: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    price: Money | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    fees: Money = Field(default=Decimal(0), ge=0, le=Decimal("1000000000"))
    amount: Money | None = Field(default=None, gt=0, le=Decimal("1000000000000"))
    note: str | None = Field(default=None, max_length=500)


class WatchItemInput(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    target_above: Money | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    target_below: Money | None = Field(default=None, gt=0, le=Decimal("1000000000"))

    @model_validator(mode="after")
    def check_levels(self):
        if self.target_above is not None and self.target_below is not None and self.target_above <= self.target_below:
            raise ValueError("Above level must exceed below level")
        return self


class PortfolioRow(BaseModel):
    id: str
    name: str
    created_at: datetime
    entry_count: int


class WatchlistRow(BaseModel):
    id: str
    name: str
    created_at: datetime
    item_count: int


class QuoteOut(BaseModel):
    close: float | None
    price_date: date | None
    change_pct: float | None


class HoldingOut(BaseModel):
    ticker: str
    quantity: float
    cost_basis: float
    average_cost: float
    close: float | None
    price_date: date | None
    market_value: float | None
    unrealized_pnl: float | None
    weight_pct: float | None


class EntryOut(BaseModel):
    id: str
    kind: str
    trade_date: date
    ticker: str | None
    quantity: float | None
    price: float | None
    fees: float
    amount: float | None
    note: str | None


class PortfolioDetail(BaseModel):
    id: str
    name: str
    currency: Literal["INR"] = "INR"
    cash: float
    net_contributions: float
    market_value: float
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    unpriced_count: int
    holdings: list[HoldingOut]
    entries: list[EntryOut]


class WatchItemOut(QuoteOut):
    ticker: str
    note: str | None
    target_above: float | None
    target_below: float | None
    alert: Literal["above", "below"] | None


class WatchlistDetail(BaseModel):
    id: str
    name: str
    items: list[WatchItemOut]


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def num(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


async def portfolio_for(session: AsyncSession, user_id: str, portfolio_id: UUID, *, lock: bool = False) -> PortfolioAccount:
    query = select(PortfolioAccount).where(PortfolioAccount.id == str(portfolio_id), PortfolioAccount.user_id == user_id)
    account = await session.scalar(query.with_for_update() if lock else query)
    if account is None:
        raise HTTPException(404, "Portfolio not found")
    return account


async def watchlist_for(session: AsyncSession, user_id: str, watchlist_id: UUID) -> Watchlist:
    watchlist = await session.scalar(select(Watchlist).where(
        Watchlist.id == str(watchlist_id), Watchlist.user_id == user_id))
    if watchlist is None:
        raise HTTPException(404, "Watchlist not found")
    return watchlist


async def known_ticker(session: AsyncSession, ticker: str) -> str:
    value = ticker.strip().upper()
    if not value or len(value) > 40 or not await session.scalar(select(Symbology.ticker).where(Symbology.ticker == value)):
        raise HTTPException(422, "Choose a ticker in the local securities directory")
    return value


async def quotes(session: AsyncSession, tickers: list[str]) -> dict[str, QuoteOut]:
    if not tickers:
        return {}
    now = monotonic()
    pending = [ticker for ticker in set(tickers) if ticker not in _quote_cache or _quote_cache[ticker][0] <= now]
    if not pending:
        return {ticker: _quote_cache[ticker][1] for ticker in tickers}
    async def read(symbols: list[str], window: str):
        return (await session.execute(text(f"""
        SELECT t.ticker, p.date, p.close FROM unnest(CAST(:tickers AS text[])) AS t(ticker)
        LEFT JOIN LATERAL (
            SELECT date, close FROM prices_daily
            WHERE ticker=t.ticker AND date<=CURRENT_DATE AND {window} AND known_date<=CURRENT_DATE
              AND close>0 AND volume>0 AND source IN ('eodhd','nse_bhavcopy')
            ORDER BY date DESC, (source='eodhd') DESC, known_date DESC LIMIT 8
        ) p ON true
        ORDER BY t.ticker, p.date DESC
    """), {"tickers": sorted(set(symbols))})).all()
    rows = await read(pending, "date >= CURRENT_DATE - INTERVAL '14 days'")
    grouped: dict[str, list] = {ticker: [] for ticker in pending}
    for ticker, price_date, close in rows:
        if price_date is not None and len(grouped[ticker]) < 2 and all(day != price_date for day, _ in grouped[ticker]):
            grouped[ticker].append((price_date, close))
    missing = [ticker for ticker, values in grouped.items() if len(values) < 2]
    if missing:
        for ticker, price_date, close in await read(missing, "date < CURRENT_DATE - INTERVAL '14 days'"):
            if price_date is not None and len(grouped[ticker]) < 2 and all(day != price_date for day, _ in grouped[ticker]):
                grouped[ticker].append((price_date, close))
    result = {}
    for ticker, values in grouped.items():
        last = values[0] if values else None
        previous = values[1] if len(values) > 1 else None
        result[ticker] = QuoteOut(close=last[1] if last else None, price_date=last[0] if last else None,
            change_pct=100 * (last[1] / previous[1] - 1) if last and previous else None)
    for ticker, quote in result.items():
        _quote_cache[ticker] = (now + 120, quote)
    return {ticker: _quote_cache[ticker][1] for ticker in tickers}


async def entries_for(session: AsyncSession, portfolio_id: str) -> list[PortfolioEntry]:
    return list((await session.scalars(select(PortfolioEntry).where(PortfolioEntry.portfolio_id == portfolio_id)
        .order_by(PortfolioEntry.trade_date, PortfolioEntry.created_at, PortfolioEntry.id))).all())


def ledger_rows(entries: list[PortfolioEntry]) -> list[dict]:
    return [{key: getattr(entry, key) for key in
        ("id", "trade_date", "created_at", "kind", "ticker", "quantity", "price", "fees", "amount")}
        for entry in entries]


def valid_ledger(entries: list[PortfolioEntry]) -> dict:
    try:
        return calculate(ledger_rows(entries))
    except LedgerError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/portfolios", response_model=list[PortfolioRow])
async def list_portfolios(user: CurrentUser, session: Session):
    rows = (await session.execute(select(PortfolioAccount.id, PortfolioAccount.name, PortfolioAccount.created_at,
        func.count(PortfolioEntry.id)).outerjoin(PortfolioEntry).where(PortfolioAccount.user_id == user.id)
        .group_by(PortfolioAccount.id).order_by(PortfolioAccount.created_at))).all()
    return [PortfolioRow(id=id, name=name, created_at=created, entry_count=count) for id, name, created, count in rows]


@router.post("/portfolios", response_model=PortfolioRow, status_code=201)
async def create_portfolio(body: PortfolioInput, user: CurrentUser, session: Session):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Portfolio name is required")
    if body.initial_date and body.initial_date > today():
        raise HTTPException(422, "Opening cash date cannot be in the future")
    account = PortfolioAccount(user_id=user.id, name=name)
    session.add(account)
    await session.flush()
    if body.initial_cash:
        session.add(PortfolioEntry(portfolio_id=account.id, kind="deposit", amount=body.initial_cash,
            trade_date=body.initial_date or today()))
    await session.commit()
    await session.refresh(account)
    return PortfolioRow(id=account.id, name=account.name, created_at=account.created_at,
        entry_count=1 if body.initial_cash else 0)


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioRow)
async def rename_portfolio(portfolio_id: UUID, body: NameInput, user: CurrentUser, session: Session):
    account = await portfolio_for(session, user.id, portfolio_id)
    if not body.name.strip():
        raise HTTPException(422, "Portfolio name is required")
    account.name = body.name.strip()
    await session.commit()
    count = await session.scalar(select(func.count()).select_from(PortfolioEntry).where(PortfolioEntry.portfolio_id == account.id))
    return PortfolioRow(id=account.id, name=account.name, created_at=account.created_at, entry_count=count or 0)


@router.delete("/portfolios/{portfolio_id}", status_code=204)
async def delete_portfolio(portfolio_id: UUID, user: CurrentUser, session: Session):
    account = await portfolio_for(session, user.id, portfolio_id, lock=True)
    if await session.scalar(select(PortfolioEntry.id).where(PortfolioEntry.portfolio_id == account.id).limit(1)):
        raise HTTPException(409, "Delete transactions before deleting this portfolio")
    await session.delete(account)
    await session.commit()


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioDetail)
async def portfolio_detail(portfolio_id: UUID, user: CurrentUser, session: Session):
    account = await portfolio_for(session, user.id, portfolio_id)
    entries = await entries_for(session, account.id)
    ledger = valid_ledger(entries)
    prices = await quotes(session, list(ledger["holdings"]))
    holdings = []
    market_value = 0.0
    unrealized = 0.0
    unpriced = 0
    for ticker, holding in ledger["holdings"].items():
        quote = prices[ticker]
        qty, basis = float(holding["quantity"]), float(holding["cost_basis"])
        value = qty * quote.close if quote.close is not None else None
        if value is None:
            unpriced += 1
        else:
            market_value += value
            unrealized += value - basis
        holdings.append(HoldingOut(ticker=ticker, quantity=qty, cost_basis=basis, average_cost=basis / qty,
            close=quote.close, price_date=quote.price_date, market_value=value,
            unrealized_pnl=value - basis if value is not None else None, weight_pct=None))
    for holding in holdings:
        if holding.market_value is not None and market_value:
            holding.weight_pct = 100 * holding.market_value / market_value
    holdings.sort(key=lambda row: row.market_value or 0, reverse=True)
    cash = float(ledger["cash"])
    contributions = float(ledger["net_contributions"])
    return PortfolioDetail(id=account.id, name=account.name, cash=cash, net_contributions=contributions,
        market_value=market_value, total_equity=cash + market_value, realized_pnl=float(ledger["realized_pnl"]),
        unrealized_pnl=unrealized, total_pnl=cash + market_value - contributions,
        unpriced_count=unpriced, holdings=holdings,
        entries=[EntryOut(id=entry.id, kind=entry.kind, trade_date=entry.trade_date, ticker=entry.ticker,
            quantity=num(entry.quantity), price=num(entry.price), fees=float(entry.fees or 0),
            amount=num(entry.amount), note=entry.note) for entry in reversed(entries)])


@router.post("/portfolios/{portfolio_id}/entries", response_model=EntryOut, status_code=201)
async def add_entry(portfolio_id: UUID, body: EntryInput, user: CurrentUser, session: Session):
    account = await portfolio_for(session, user.id, portfolio_id, lock=True)
    if body.trade_date > today():
        raise HTTPException(422, "Transaction date cannot be in the future")
    trade = body.kind in {"buy", "sell"}
    if trade and (body.ticker is None or body.quantity is None or body.price is None or body.amount is not None):
        raise HTTPException(422, "A trade needs ticker, quantity and price, without cash amount")
    if not trade and (body.amount is None or body.ticker is not None or body.quantity is not None or body.price is not None or body.fees):
        raise HTTPException(422, "A cash entry needs only an amount")
    ticker = await known_ticker(session, body.ticker) if trade else None
    entry = PortfolioEntry(portfolio_id=account.id, kind=body.kind, ticker=ticker,
        quantity=body.quantity, price=body.price, fees=body.fees, amount=body.amount,
        trade_date=body.trade_date, note=body.note.strip() if body.note else None)
    entries = await entries_for(session, account.id)
    entry.created_at = datetime.now(ZoneInfo("UTC"))
    entry.id = str(uuid4())
    valid_ledger([*entries, entry])
    session.add(entry)
    await session.commit()
    return EntryOut(id=entry.id, kind=entry.kind, trade_date=entry.trade_date, ticker=entry.ticker,
        quantity=num(entry.quantity), price=num(entry.price), fees=float(entry.fees), amount=num(entry.amount), note=entry.note)


@router.delete("/portfolios/{portfolio_id}/entries/{entry_id}", status_code=204)
async def delete_entry(portfolio_id: UUID, entry_id: UUID, user: CurrentUser, session: Session):
    account = await portfolio_for(session, user.id, portfolio_id, lock=True)
    entries = await entries_for(session, account.id)
    target = next((entry for entry in entries if entry.id == str(entry_id)), None)
    if target is None:
        raise HTTPException(404, "Transaction not found")
    valid_ledger([entry for entry in entries if entry.id != target.id])
    await session.delete(target)
    await session.commit()


@router.get("/watchlists", response_model=list[WatchlistRow])
async def list_watchlists(user: CurrentUser, session: Session):
    rows = (await session.execute(select(Watchlist.id, Watchlist.name, Watchlist.created_at,
        func.count(WatchlistItem.ticker)).outerjoin(WatchlistItem).where(Watchlist.user_id == user.id)
        .group_by(Watchlist.id).order_by(Watchlist.created_at))).all()
    return [WatchlistRow(id=id, name=name, created_at=created, item_count=count) for id, name, created, count in rows]


@router.post("/watchlists", response_model=WatchlistRow, status_code=201)
async def create_watchlist(body: NameInput, user: CurrentUser, session: Session):
    if not body.name.strip():
        raise HTTPException(422, "Watchlist name is required")
    watchlist = Watchlist(user_id=user.id, name=body.name.strip())
    session.add(watchlist)
    await session.commit()
    await session.refresh(watchlist)
    return WatchlistRow(id=watchlist.id, name=watchlist.name, created_at=watchlist.created_at, item_count=0)


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistRow)
async def rename_watchlist(watchlist_id: UUID, body: NameInput, user: CurrentUser, session: Session):
    watchlist = await watchlist_for(session, user.id, watchlist_id)
    if not body.name.strip():
        raise HTTPException(422, "Watchlist name is required")
    watchlist.name = body.name.strip()
    await session.commit()
    count = await session.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id))
    return WatchlistRow(id=watchlist.id, name=watchlist.name, created_at=watchlist.created_at, item_count=count or 0)


@router.delete("/watchlists/{watchlist_id}", status_code=204)
async def delete_watchlist(watchlist_id: UUID, user: CurrentUser, session: Session):
    watchlist = await watchlist_for(session, user.id, watchlist_id)
    await session.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id))
    await session.delete(watchlist)
    await session.commit()


@router.get("/watchlists/{watchlist_id}", response_model=WatchlistDetail)
async def watchlist_detail(watchlist_id: UUID, user: CurrentUser, session: Session):
    watchlist = await watchlist_for(session, user.id, watchlist_id)
    items = list((await session.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id)
        .order_by(WatchlistItem.added_at, WatchlistItem.ticker))).all())
    prices = await quotes(session, [item.ticker for item in items])
    result = []
    for item in items:
        quote = prices[item.ticker]
        above, below = num(item.target_above), num(item.target_below)
        alert = "above" if quote.close is not None and above is not None and quote.close >= above else (
            "below" if quote.close is not None and below is not None and quote.close <= below else None)
        result.append(WatchItemOut(ticker=item.ticker, note=item.note, target_above=above, target_below=below,
            close=quote.close, price_date=quote.price_date, change_pct=quote.change_pct, alert=alert))
    return WatchlistDetail(id=watchlist.id, name=watchlist.name, items=result)


@router.put("/watchlists/{watchlist_id}/items/{ticker}", response_model=WatchItemOut)
async def save_watch_item(watchlist_id: UUID, ticker: str, body: WatchItemInput, user: CurrentUser, session: Session):
    watchlist = await watchlist_for(session, user.id, watchlist_id)
    ticker = await known_ticker(session, ticker)
    item = await session.get(WatchlistItem, (watchlist.id, ticker))
    if item is None:
        item = WatchlistItem(watchlist_id=watchlist.id, ticker=ticker)
        session.add(item)
    item.note = body.note.strip() if body.note else None
    item.target_above = body.target_above
    item.target_below = body.target_below
    await session.commit()
    quote = (await quotes(session, [ticker]))[ticker]
    above, below = num(item.target_above), num(item.target_below)
    alert = "above" if quote.close is not None and above is not None and quote.close >= above else (
        "below" if quote.close is not None and below is not None and quote.close <= below else None)
    return WatchItemOut(ticker=ticker, note=item.note, target_above=above, target_below=below,
        close=quote.close, price_date=quote.price_date, change_pct=quote.change_pct, alert=alert)


@router.delete("/watchlists/{watchlist_id}/items/{ticker}", status_code=204)
async def remove_watch_item(watchlist_id: UUID, ticker: str, user: CurrentUser, session: Session):
    watchlist = await watchlist_for(session, user.id, watchlist_id)
    result = await session.execute(delete(WatchlistItem).where(
        WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.ticker == ticker.strip().upper()))
    if not result.rowcount:
        raise HTTPException(404, "Watchlist item not found")
    await session.commit()
