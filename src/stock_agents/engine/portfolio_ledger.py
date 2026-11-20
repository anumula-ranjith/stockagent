"""Deterministic FIFO accounting for user-entered INR equity transactions."""

from collections import defaultdict
from decimal import Decimal

ZERO = Decimal("0")
EPS = Decimal("0.000001")


class LedgerError(ValueError):
    pass


def calculate(entries: list[dict]) -> dict:
    cash = ZERO
    contributions = ZERO
    realized = ZERO
    lots: dict[str, list[list[Decimal]]] = defaultdict(list)
    for entry in sorted(entries, key=lambda row: (row["trade_date"], row["created_at"], str(row["id"]))):
        kind = entry["kind"]
        ticker = entry.get("ticker")
        quantity = Decimal(entry.get("quantity") or 0)
        price = Decimal(entry.get("price") or 0)
        fees = Decimal(entry.get("fees") or 0)
        amount = Decimal(entry.get("amount") or 0)
        if kind == "deposit":
            cash += amount
            contributions += amount
        elif kind == "withdrawal":
            cash -= amount
            contributions -= amount
        elif kind == "buy":
            cash -= quantity * price + fees
            lots[ticker].append([quantity, (quantity * price + fees) / quantity])
        elif kind == "sell":
            remaining = quantity
            basis = ZERO
            for lot in lots[ticker]:
                take = min(lot[0], remaining)
                lot[0] -= take
                remaining -= take
                basis += take * lot[1]
                if remaining <= EPS:
                    break
            if remaining > EPS:
                raise LedgerError(f"Insufficient {ticker} shares on {entry['trade_date']}.")
            lots[ticker] = [lot for lot in lots[ticker] if lot[0] > EPS]
            proceeds = quantity * price - fees
            cash += proceeds
            realized += proceeds - basis
        else:
            raise LedgerError("Unsupported transaction type.")
        if cash < -EPS:
            raise LedgerError(f"Insufficient cash on {entry['trade_date']}.")
    holdings = {}
    for ticker, ticker_lots in lots.items():
        quantity = sum((lot[0] for lot in ticker_lots), ZERO)
        if quantity > EPS:
            holdings[ticker] = {"quantity": quantity, "cost_basis": sum((lot[0] * lot[1] for lot in ticker_lots), ZERO)}
    return {"cash": cash, "net_contributions": contributions, "realized_pnl": realized, "holdings": holdings}
