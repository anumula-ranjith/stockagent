# Personal portfolios and watchlists

The **Portfolio** and **Watchlists** pages are private to each signed-in user. They use the existing PostgreSQL database and the locally stored EODHD/NSE daily prices. Run `python -m alembic -c alembic.ini upgrade head` after updating the app.

## Portfolio workflow

1. Create a named INR portfolio. Enter opening cash and its actual date if you want to record older trades.
2. Add deposits, withdrawals, buys and sells with their execution dates. Buys need available cash; sells need shares already held on that date.
3. Review holdings, average FIFO cost, available cash, realized and unrealized P&L, latest stored price date, and allocation weight.
4. Correct an entry by deleting it and recording the replacement. The server rejects deletions that would leave later entries with negative cash or an oversold position.
5. Export the activity ledger as CSV for your own records. An account can have several independent portfolios.

All trade math uses `Decimal`; quantities and monetary amounts are stored as PostgreSQL `NUMERIC`. Buy fees enter the cost basis and sell fees reduce proceeds. Total P&L is equity less net deposits. If a holding has no usable local close, its value is omitted and the page shows a coverage warning. This is a manual, long-only tracker; it does not execute orders. Broker holdings are shown separately to avoid double counting.

## Watchlist workflow

Create multiple named lists, add stocks from the list or a stock detail page, and save a note plus optional upper and lower price levels. The status column evaluates those levels against the latest locally stored close when the list loads. Levels are in-app indicators; they do not send email or mobile notifications. Lists can be renamed, exported as CSV, and deleted.

## Angel One read-only sync

The Portfolio page can fetch Angel One settled holdings and the current day's trade book. Enter your SmartAPI key, client code, password or MPIN, and current TOTP. The server uses them once for login and read requests and discards the credentials and session token. Only normalized holdings and trade data are saved to your private broker snapshot. You can clear that snapshot from the page. A broker snapshot is separate from manual cash, trades, and FIFO P&L; the page compares share quantities without importing fills into the ledger.

Angel One documents that the trade book covers the current day, so it cannot reconstruct older trades or cash flows. The app makes no order, modification, cancellation, or GTT requests. The server may set `ANGEL_ONE_PUBLIC_IP` if Angel One requires a specific value in its request header. Live sync requires working SmartAPI credentials and external network access; tests use mocked responses.
