from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from stock_agents.api import auth, main, screen_export
from stock_agents.common.mail import MailDeliveryError


def test_filtered_workbook_and_email_attachment(monkeypatch):
    sample = dict(close=101.25, cap="mid", heikin_ashi_color="green", heikin_ashi_transition="red_to_green")
    version = "a" * 64
    snapshot = {"asof": "2026-11-19", "export_version": version,
                "rows": [dict(sample, ticker=ticker) for ticker in ("AAA", "BBB", "CCC")]}
    monkeypatch.setattr(screen_export, "screen_snapshot", lambda _: snapshot)
    monkeypatch.setitem(main.app.dependency_overrides, main.universe, lambda: [{"ticker": "CCC", "company_name": "=example"}])
    messages = []
    monkeypatch.setattr(screen_export, "deliver_message", messages.append)
    client = TestClient(main.app)
    body = {"screen": {}, "tickers": ["CCC", "AAA"], "export_version": version}
    assert client.post("/screener/export", json=body).status_code == 401
    user = auth.UserOut(id="export-test", email="researcher@example.org", is_admin=False, email_verified=True)
    monkeypatch.setitem(main.app.dependency_overrides, auth.get_current_user, lambda: user)
    download = client.post("/screener/export", json=body)
    assert download.status_code == 200 and download.headers["content-type"] == screen_export.XLSX
    def sheet(content):
        return load_workbook(BytesIO(content)).active
    results = sheet(download.content)
    assert [cell.value for cell in results["A"]] == ["Ticker", "CCC", "AAA"]
    assert results["F2"].value == 101.25 and results["B2"].data_type == "s"
    assert results["N2"].value == "Red → Green"
    email = {**body, "recipient": "recipient@example.org"}
    assert client.post("/screener/email", json=email).status_code == 204
    assert len(messages) == 1 and messages[0]["To"] == email["recipient"]
    attachment, = messages[0].iter_attachments()
    assert attachment.get_filename() == "screener-2026-11-19.xlsx"
    assert list(sheet(attachment.get_payload(decode=True)).values) == list(results.values)
    assert client.post("/screener/export", json={**body, "export_version": "b"*64}).status_code == 409
    assert client.post("/screener/export", json={**body, "tickers": ["ZZZ"]}).status_code == 422
    assert client.post("/screener/email", json={**body, "recipient": "invalid"}).status_code == 422

    def unavailable(message):
        raise MailDeliveryError("Email service unavailable")
    monkeypatch.setattr(screen_export, "deliver_message", unavailable)
    assert client.post("/screener/email", json=email).status_code == 503
