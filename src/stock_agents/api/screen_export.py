"""Excel exports for the signed-in user's current screener results."""
from email.message import EmailMessage
from io import BytesIO
from typing import Annotated

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, EmailStr, Field

from stock_agents.api.screener import Screen, screen_snapshot
from stock_agents.common.mail import MailDeliveryError, deliver_message

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUMNS = (
    ("ticker", "Ticker"), ("company_name", "Company name"), ("sector", "Sector"),
    ("cap", "Cap segment"), ("industry", "Industry"), ("close", "Latest price (₹)"),
    ("below_high_pct", "% below high"), ("below_low_pct", "% below low"),
    ("above_high_pct", "% above high"), ("above_low_pct", "% above low"),
    ("high_52w", "52w high"), ("low_52w", "52w low"),
    ("heikin_ashi_color", "Heikin Ashi candle"), ("heikin_ashi_transition", "Heikin Ashi turn"),
)


class ScreenExport(BaseModel):
    screen: Screen
    export_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    tickers: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(min_length=1, max_length=2000)


class ScreenEmail(ScreenExport):
    recipient: EmailStr


def workbook(body: ScreenExport, companies: list[dict]) -> tuple[str, bytes]:
    snapshot = screen_snapshot(body.screen)
    if snapshot["export_version"] != body.export_version:
        raise HTTPException(409, "The results have changed. Refresh the screener and try again.")
    rows = {row["ticker"]: row for row in snapshot["rows"]}
    if len(set(body.tickers)) != len(body.tickers) or any(t not in rows for t in body.tickers):
        raise HTTPException(422, "Select stocks from the current screener results.")
    identities = {row["ticker"]: row for row in companies}
    book = Workbook()
    sheet = book.active
    sheet.title = "Screener results"
    sheet.append([label for _, label in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="244465")
    turns = {"red_to_green": "Red → Green", "green_to_red": "Green → Red", "none": "None"}
    for index, ticker in enumerate(body.tickers, 2):
        row = {**identities.get(ticker, {}), **rows[ticker]}
        if row["cap"]:
            row["cap"] = row["cap"].capitalize() + " cap"
        if row["heikin_ashi_color"]:
            row["heikin_ashi_color"] = row["heikin_ashi_color"].capitalize()
        row["heikin_ashi_transition"] = turns.get(row["heikin_ashi_transition"])
        for column, (key, _) in enumerate(COLUMNS, 1):
            cell = sheet.cell(index, column, row.get(key))
            if isinstance(cell.value, str):
                cell.data_type = "s"
            elif cell.value is not None:
                cell.number_format = "#,##0.00"
    for col, (key, label) in enumerate(COLUMNS, 1):
        sheet.column_dimensions[get_column_letter(col)].width = 34 if key in {"company_name", "sector", "industry"} else max(15, len(label) + 3)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    book.save(output)
    return f"screener-{snapshot['asof']}.xlsx", output.getvalue()


def email_workbook(body: ScreenEmail, companies: list[dict], requested_by: str) -> None:
    name, content = workbook(body, companies)
    message = EmailMessage()
    message["To"] = str(body.recipient)
    message["Subject"] = "QUANTORA screener results"
    message.set_content(f"{requested_by} shared {len(body.tickers)} stocks from the QUANTORA screener. "
                        "The attached Excel workbook contains the filtered results.")
    message.add_attachment(content, maintype="application", subtype=XLSX.split("/", 1)[1], filename=name)
    try:
        deliver_message(message)
    except MailDeliveryError as exc:
        raise HTTPException(503, str(exc)) from exc
