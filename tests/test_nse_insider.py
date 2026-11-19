from datetime import date

from stock_agents.ingest.nse_insider import parse_filing


def test_nse_insider_keeps_inr_consideration_and_excludes_pledges():
    def fact(name, value, context, attrs=""):
        return f'<ix:nonNumeric name="co:{name}" contextRef="{context}" {attrs}>{value}</ix:nonNumeric>'

    def disclosure(context, kind, mode):
        return "".join([
            fact("TypeOfInstrument", "Equity", context),
            fact("CategoryOfPerson", "Promoter", context),
            fact("SecuritiesAcquiredOrDisposedNumberOfSecurity", "10,000", context),
            fact("SecuritiesAcquiredOrDisposedValueOfSecurity", "1,250", context, 'unitRef="INR" scale="3"'),
            fact("SecuritiesAcquiredOrDisposedTransactionType", kind, context),
            fact("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate", "17-11-2026", context),
            fact("ModeOfAcquisitionOrDisposal", mode, context),
        ])

    document = fact("Symbol", "ABC", "MainI")
    document += disclosure("Disclosure1", "Acquisition", "Market Purchase")
    document += disclosure("Disclosure2", "Pledge Revoke", "Pledge Release")
    document += disclosure("Disclosure3", "Disposal", "Market Sale")
    rows = parse_filing(document, "ABC", "100", date(2026, 11, 19))
    assert [row["tx_type"] for row in rows] == ["BUY", "SELL"]
    assert all(row["value_inr"] == 1_250_000 and row["price"] == 125 for row in rows)
    assert all("value_usd" not in row and row["known_date"] == date(2026, 11, 19) for row in rows)
