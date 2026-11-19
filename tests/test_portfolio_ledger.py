from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_agents.engine.portfolio_ledger import LedgerError, calculate


def row(index, day, kind, ticker=None, quantity=None, price=None, amount=None, fees=0):
    return dict(id=str(index), trade_date=date(2026, 1, day),
        created_at=datetime(2026, 1, day, index, tzinfo=UTC),
        kind=kind, ticker=ticker, quantity=quantity, price=price, amount=amount, fees=fees)


def test_fifo_realized_and_remaining_basis():
    entries = [row(1, 1, "deposit", amount=10000), row(2, 2, "buy", "ABC", 10, 100, fees=10),
        row(3, 3, "buy", "ABC", 10, 120), row(4, 4, "sell", "ABC", 12, 130, fees=6)]
    result = calculate(entries)
    assert result["cash"] == Decimal("9344")
    assert result["realized_pnl"] == Decimal("304")
    assert result["holdings"]["ABC"]["quantity"] == Decimal("8")
    assert result["holdings"]["ABC"]["cost_basis"] == Decimal("960")


def test_rejects_oversell_and_negative_cash_even_when_entries_arrive_out_of_order():
    with pytest.raises(LedgerError, match="Insufficient ABC shares"):
        calculate([row(1, 1, "deposit", amount=1000), row(2, 2, "sell", "ABC", 1, 100)])
    with pytest.raises(LedgerError, match="Insufficient cash"):
        calculate([row(2, 2, "deposit", amount=1000), row(1, 1, "buy", "ABC", 1, 100)])


def test_withdrawal_and_buy_fees_reconcile_cash():
    result = calculate([row(1, 1, "deposit", amount=1000), row(2, 2, "buy", "ABC", 2, 100, fees=5),
        row(3, 3, "withdrawal", amount=100)])
    assert result["cash"] == Decimal("695")
    assert result["net_contributions"] == Decimal("900")
    assert result["holdings"]["ABC"]["cost_basis"] == Decimal("205")
