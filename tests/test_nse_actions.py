from datetime import date

import pytest

from stock_agents.sources.nse import NSEClient, parse_corporate_actions, parse_previous_closes

START = date(2026, 5, 14)
END = date(2026, 11, 18)
ISIN = "INE2OVN25015"


def _row(subject, **overrides):
    return dict(symbol="BAGMANE", isin=ISIN, exDate="05-Nov-2026", series="RR",
                subject=subject, **overrides)


def test_distribution_uses_all_components_exactly_once():
    subject = "Distribution - Rs 5.70 Per Unit Consists Of Rs 1.72 Per Unit As Dividend/ Rs 1.54 Per Unit As Interest/Rs 2.24 Per Unit Repayemt Of Spv And Ncd/ Re 0.20 Per Unit Interest On Fd"
    records = parse_corporate_actions([_row(subject)], "BAGMANE", START, END, ISIN)
    assert records == [dict(ex_date=date(2026, 11, 5), action_type="distribution", value=5.7,
                            subject=subject)]
    with pytest.raises(ValueError, match="components"):
        parse_corporate_actions([_row(subject.replace("Rs 5.70", "Rs 5.71"))], "BAGMANE", START, END, ISIN)


@pytest.mark.parametrize("compound", ["Bonus 1:1", "Demerger", "Rights 1:2", "Share Split 1:5"])
def test_distribution_rejects_compound_share_actions(compound):
    with pytest.raises(ValueError, match="Unsupported"):
        parse_corporate_actions([_row("Distribution - Rs 5 Per Unit / " + compound)],
                               "BAGMANE", START, END, ISIN)


@pytest.mark.parametrize("field,value", [("isin", "INE05HV01027"), ("symbol", "OTHER"),
                                        ("exDate", "01-Jan-2026")])
def test_actions_validate_identity_and_date_range(field, value):
    row = _row("Dividend - Rs 1.06 Per Share")
    row[field] = value
    with pytest.raises(ValueError):
        parse_corporate_actions([row], "BAGMANE", START, END, ISIN)


def test_empty_actions_and_unsupported_demerger():
    assert parse_corporate_actions([], "BAGMANE", START, END, ISIN) == []
    with pytest.raises(ValueError, match="Unsupported"):
        parse_corporate_actions([_row("Demerger")], "BAGMANE", START, END, ISIN)
    with pytest.raises(ValueError, match="duplicate"):
        parse_corporate_actions([_row("Dividend - Rs 1.06 Per Share")] * 2,
                               "BAGMANE", START, END, ISIN)
    with pytest.raises(ValueError, match="range"):
        parse_corporate_actions([], "BAGMANE", END, START, ISIN)


@pytest.mark.parametrize("subject,kind,value", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", 5.),
    ("Bonus 1:2", "bonus", 0.5),
    ("Annual General Meeting/Dividend - Rs 1.06 Per Share", "dividend", 1.06),
])
def test_action_ratio_direction(subject, kind, value):
    [action] = parse_corporate_actions([_row(subject)], "BAGMANE", START, END, ISIN)
    assert (action["action_type"], action["value"]) == (kind, value)


def test_corporate_action_session_initializes_once(monkeypatch):
    calls = []

    class Response:
        url = "https://www.nseindia.com/api/corporates-corporateActions"

        def raise_for_status(self):
            pass

        def json(self):
            return [_row("Dividend - Rs 1.06 Per Share")]

    client = NSEClient()

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(client.session, "get", get)
    assert client.corporate_actions("BAGMANE", END, START, ISIN) == []
    assert calls == []
    for _ in range(2):
        actions = client.corporate_actions("BAGMANE", START, END, ISIN)
        assert actions[0]["source_url"] == Response.url
    assert len(calls) == 3
    assert calls[1][1]["params"] == dict(index="equities", symbol="BAGMANE",
                                        from_date="14-05-2026", to_date="18-11-2026")


def test_previous_close_requires_exact_date_identity_and_valid_price():
    header = "TradDt,TckrSymb,SctySrs,ISIN,PrvsClsgPric\n"
    row = "2026-11-05,BAGMANE,RR,INE2OVN25015,105.93\n"
    assert parse_previous_closes(header + row, date(2026, 11, 5)) == {
        "BAGMANE": {"close": 105.93, "isin": ISIN},
    }
    for invalid in (row.replace("105.93", "0"), row.replace("105.93", "nan"), row.replace("105.93", "")):
        assert parse_previous_closes(header + invalid, date(2026, 11, 5)) == {}
    for invalid in (row.replace(ISIN, ""), row.replace("2026-11-05", "2026-11-04"), row + row):
        with pytest.raises(ValueError):
            parse_previous_closes(header + invalid, date(2026, 11, 5))
