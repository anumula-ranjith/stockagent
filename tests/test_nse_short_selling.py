from datetime import date

import pytest

from stock_agents.ingest.nse_short_selling import parse_report


def test_short_sales_use_trade_date_and_aggregate_rows():
    report = (
        '"Security Name","Symbol Name","Trade Date","Quantity"\n'
        '"Example","ABC","17-Nov-2026","1,500"\n'
        '"Example","ABC","17-Nov-26","50"\n'
    )
    assert parse_report(report, date(2026, 11, 18)) == {(date(2026, 11, 17), "ABC"): 1550}
    with pytest.raises(ValueError, match="Invalid short-selling report row"):
        parse_report(report, date(2026, 11, 16))
