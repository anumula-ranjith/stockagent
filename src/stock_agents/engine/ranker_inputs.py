"""Point-in-time inputs for the interactive Nifty 500 ranker."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from stock_agents.common.price_basis import indicator_closes
from stock_agents.storage.warehouse import Warehouse

# Keep licensed vendor fields out of the interactive factor tables and downloads.
PUBLIC_SOURCE = "LOWER(TRIM(COALESCE(source, ''))) NOT LIKE 'factset%'"
MEMBERS = """SELECT DISTINCT ticker FROM index_membership
             WHERE index_code = 'NIFTY500' AND known_on <= ? AND joined_on <= ?
             AND (left_on IS NULL OR left_on > ?) AND ticker NOT LIKE 'DUMMY%'"""


def _frame(conn, query, args, columns):
    return pd.DataFrame.from_records(conn.execute(query, args).fetchall(), columns=columns)


def price_factors(bars: pd.DataFrame, tickers: pd.Index) -> pd.DataFrame:
    """Compute each security on its own trading sessions.

    A special trading session may have bars for only part of the universe.
    Pivoting all securities onto one date index would turn that legitimate
    absence into a missing observation in every rolling window.
    """
    if bars.empty:
        return pd.DataFrame(index=tickers)
    latest_session = bars.date.max()
    frames = [
        _price_factors_aligned(group, pd.Index([ticker], name=tickers.name))
        for ticker, group in bars.groupby("ticker", sort=False)
    ]
    out = pd.concat(frames).reindex(tickers)
    # Do not score a stock whose latest bar predates the universe's close.
    current = set(bars.loc[bars.date == latest_session, "ticker"])
    out.loc[~out.index.isin(current), :] = np.nan
    out["rel_str"] = out["ret_3m"] - out["ret_3m"].mean()
    return out


def _price_factors_aligned(bars: pd.DataFrame, tickers: pd.Index) -> pd.DataFrame:
    """Calculate factors for bars sharing one session calendar."""
    out = pd.DataFrame(index=tickers)
    if bars.empty:
        return out
    wide = bars.pivot(
        index="date", columns="ticker", values=["adj_close", "close", "high", "low", "volume"]
    ).sort_index()
    px = wide["adj_close"].astype(float).where(lambda x: x > 0)
    scale = px / wide["close"].replace(0, np.nan)
    high, low, volume = wide["high"] * scale, wide["low"] * scale, wide["volume"]
    p = px.iloc[-1]

    def last(frame):
        return frame.iloc[-1]

    def lag(days):
        return px.iloc[-1 - days] if len(px) > days else pd.Series(np.nan, index=px.columns)

    def mean(frame, window):
        return last(frame.rolling(window).mean())

    delta = px.diff()
    gain = mean(delta.clip(lower=0), 14)
    loss = mean(-delta.clip(upper=0), 14)
    out["rsi14"] = (100 * gain / (gain + loss)).mask((gain + loss) == 0, 50)

    def ema(frame, n):
        return frame.ewm(span=n, adjust=False, min_periods=n).mean()

    macd = ema(px, 12) - ema(px, 26)
    out["macd_hist"] = last(macd - ema(macd, 9)) / p
    ma50, ma200 = mean(px, 50), mean(px, 200)
    out["vs_sma50"], out["vs_sma200"] = p / ma50 - 1, p / ma200 - 1
    out["golden_cross"] = ma50 / ma200 - 1
    prev = px.shift(1)
    tr = pd.DataFrame(
        np.maximum.reduce(
            [(high - low).values, (high - prev).abs().values, (low - prev).abs().values]
        ),
        index=px.index,
        columns=px.columns,
    )
    up, down = high.diff(), -low.diff()
    plus = up.where((up > down) & (up > 0), 0).where(up.notna()).rolling(14).mean()
    minus = down.where((down > up) & (down > 0), 0).where(down.notna()).rolling(14).mean()
    dx = 100 * (plus - minus) / (plus + minus).replace(0, np.nan)
    out["adx14_signed"] = mean(dx.abs(), 14) * np.sign(last(dx))
    mid = mean(px, 20)
    width = 2 * last(px.rolling(20).std(ddof=0))
    out["bb_pctb"] = (p - mid + width) / (2 * width).replace(0, np.nan)
    floor = last(low.rolling(14).min())
    out["stoch_k"] = 100 * (p - floor) / (last(high.rolling(14).max()) - floor).replace(0, np.nan)
    out["vol_surge"] = last(volume) / mean(volume.shift(1), 20).replace(0, np.nan)
    out["obv_trend"] = mean(np.sign(delta) * volume, 20) / mean(volume, 20).replace(0, np.nan)
    out["atr_pct"] = mean(tr, 14) / p
    out["prox_52w_high"] = p / last(high.rolling(252).max()) - 1
    out["traded_value"] = mean(wide["close"] * volume, 20)
    for days, key in [(20, "ret_20d"), (21, "ret_1m"), (63, "ret_3m"), (126, "ret_6m")]:
        out[key] = p / lag(days) - 1
    out["ret_12_1"] = lag(21) / lag(252) - 1
    out["rel_str"] = out["ret_3m"] - out["ret_3m"].mean()
    out["accel"] = out["ret_1m"] - (lag(21) / lag(42) - 1)
    out["volatility"] = last(px.pct_change(fill_method=None).rolling(60).std()) * np.sqrt(252)
    out.loc[~p.reindex(out.index).notna(), :] = np.nan
    return out.replace([np.inf, -np.inf], np.nan)


def snapshot_inputs(
    conn: Warehouse, asof: date, *, cohort_date: date | None = None, subject: str | None = None
):
    observed = cohort_date or asof
    members = [r[0] for r in conn.execute(MEMBERS, [observed] * 3).fetchall()]
    names = pd.Index(sorted(members), name="ticker")
    if not members:
        return pd.DataFrame(index=names), None
    pool_query = MEMBERS
    pool_args = [observed] * 3
    comparison_subject = None
    if subject and subject not in names:
        directory = conn.execute(
            """SELECT s.ticker FROM symbology s WHERE s.ticker=? AND s.ticker NOT LIKE 'DUMMY%'
               AND (s.active=TRUE OR EXISTS (SELECT 1 FROM index_membership m
                  WHERE m.ticker=s.ticker AND m.index_code='NSE_FO' AND m.known_on<=?
                  AND m.joined_on<=? AND (m.left_on IS NULL OR m.left_on>?)))""",
            [subject, observed, observed, observed],
        ).fetchone()
        if not directory:
            return pd.DataFrame(index=pd.Index([], name="ticker")), None
        comparison_subject = subject
        names = pd.Index(sorted([*members, subject]), name="ticker")
        pool_query += " UNION SELECT ticker FROM symbology WHERE ticker=?"
        pool_args.append(subject)
    bars = _frame(
        conn,
        f"""WITH members AS ({pool_query})
            SELECT date,ticker,adj_close,close,high,low,volume,source FROM (
              SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.ticker, date
                ORDER BY (source='angel_one') DESC,(source='eodhd') DESC,known_date DESC,source) rn
              FROM prices_daily p JOIN members USING(ticker)
              WHERE date BETWEEN ? AND ? AND known_date<=? AND (adj_close>0 OR (source='angel_one' AND close>0)) AND volume>0 AND {PUBLIC_SOURCE}
            ) chosen WHERE rn=1""",
        pool_args + [asof - timedelta(days=420), asof, observed],
        ["date", "ticker", "adj_close", "close", "high", "low", "volume", "source"],
    )
    bars["adj_close"] = indicator_closes(bars)
    if comparison_subject and not bars.empty:
        reference_sessions = bars.loc[bars.ticker != comparison_subject, "date"]
        if not reference_sessions.empty:
            bars = bars[bars.date.isin(reference_sessions)]
    frame = price_factors(bars, names)
    if comparison_subject and "ret_3m" in frame:
        frame["rel_str"] = frame["ret_3m"] - frame.loc[members, "ret_3m"].mean()

    def latest(
        table, cols, effective="effective_date", partition="ticker", licensed=False, cutoff=asof
    ):
        # Callers supply only constant table/column identifiers.
        source_filter = "TRUE" if licensed else PUBLIC_SOURCE
        return _frame(
            conn,
            f"""SELECT {",".join(cols)} FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition} ORDER BY {effective} DESC,
                known_date DESC, source) rn FROM {table}
            WHERE {effective}<=? AND known_date<=? AND {source_filter}
            ) recent WHERE rn=1""",
            [cutoff, cutoff],
            cols,
        )

    cls = latest(
        "classification", ["ticker", "sector", "industry", "source"], cutoff=observed
    ).set_index("ticker")
    frame["sector"] = (
        cls["sector"].where(~cls["source"].isin(["nse_indices", "industry_sector_map"]), cls["industry"]).fillna(cls["sector"])
    )
    fundamentals = latest(
        "fundamentals_pit",
        ["ticker", "metric", "value", "source"],
        partition="ticker,metric",
        licensed=True,
    )
    protected = {}
    if not fundamentals.empty:
        frame = frame.join(
            fundamentals.pivot(index="ticker", columns="metric", values="value"),
            rsuffix="_reported",
        )
        for metric, group in fundamentals[
            fundamentals.source.str.strip().str.lower().str.startswith("factset")
        ].groupby("metric"):
            protected[metric] = set(group.ticker)

    news = _frame(
        conn,
        f"""SELECT ticker,effective_date,polarity,n_headlines
        FROM sentiment_daily WHERE effective_date BETWEEN ? AND ? AND known_date<=?
        AND {PUBLIC_SOURCE}""",
        [asof - timedelta(days=29), asof, asof],
        ["ticker", "day", "tone", "count"],
    )
    # A headline-level observation can fill a missing daily aggregate. The
    # aggregate takes precedence where both feeds describe the same stock-day.
    headlines = _frame(
        conn,
        f"""SELECT ticker, CAST(published_at AS DATE), AVG(polarity), COUNT(*)
            FROM news WHERE CAST(published_at AS DATE) BETWEEN ? AND ?
              AND known_date<=? AND {PUBLIC_SOURCE}
            GROUP BY ticker, CAST(published_at AS DATE)""",
        [asof - timedelta(days=29), asof, asof],
        ["ticker", "day", "tone", "count"],
    )
    if not headlines.empty:
        news = pd.concat([news, headlines], ignore_index=True).drop_duplicates(["ticker", "day"])
    if not news.empty:
        news["age"] = news["day"].map(lambda d: (asof - d).days)
        recent = news.loc[news.age < 7].copy()
        mass = recent["count"] * 2.0 ** (-recent.age / 2)
        frame["news_tone_7d"] = (recent.tone * mass).groupby(recent.ticker).sum(
            min_count=1
        ) / mass.where(recent.tone.notna()).groupby(recent.ticker).sum(min_count=1)
        frame["headlines"] = recent.groupby("ticker")["count"].sum()
        normal = news.loc[news.age >= 3].groupby("ticker")["count"].sum() / 27
        frame["news_volume"] = news.loc[news.age < 3].groupby("ticker")["count"].sum() / (
            3 * normal.replace(0, np.nan)
        )
    est = latest(
        "estimates_pit",
        ["ticker", "metric", "value", "source"],
        partition="ticker,metric",
        licensed=True,
    )
    if not est.empty:
        licensed = est.loc[est.source.str.strip().str.lower().str.startswith("factset")]
        licensed_metrics = {
            metric: set(group.ticker) for metric, group in licensed.groupby("metric")
        }
        est = est.pivot(index="ticker", columns="metric", values="value")
        if "rating_change_1m" in est:
            frame["rating_change_1m"] = est["rating_change_1m"]
            protected["rating_change_1m"] = licensed_metrics.get("rating_change_1m", set())
        if {"revisions_up_30d", "revisions_down_30d"} <= set(est.columns):
            frame["est_revisions"] = est["revisions_up_30d"] - est["revisions_down_30d"]
            protected["est_revisions"] = licensed_metrics.get(
                "revisions_up_30d", set()
            ) | licensed_metrics.get("revisions_down_30d", set())
        if "eps_fy1" in est and "eps_ttm" in frame:
            frame["forward_eps_growth"] = (
                est["eps_fy1"] / frame["eps_ttm"].where(frame["eps_ttm"] > 0) - 1
            )
            protected["forward_eps_growth"] = licensed_metrics.get(
                "eps_fy1", set()
            ) | protected.get("eps_ttm", set())
    insider = _frame(
        conn,
        f"""SELECT ticker,
        SUM(CASE WHEN UPPER(tx_type) IN ('P','BUY') THEN value_inr
                 WHEN UPPER(tx_type) IN ('S','SELL') THEN -value_inr END),
        SUM(CASE WHEN UPPER(tx_type) IN ('P','BUY') THEN value_usd
                 WHEN UPPER(tx_type) IN ('S','SELL') THEN -value_usd END)
        FROM insider_tx WHERE tx_date BETWEEN ? AND ? AND known_date<=?
          AND (superseded_on IS NULL OR superseded_on>?) AND {PUBLIC_SOURCE} GROUP BY ticker""",
        [asof - timedelta(days=89), asof, asof, asof],
        ["ticker", "inr", "usd"],
    )
    insider = insider.set_index("ticker").reindex(frame.index)
    # Each cross section must compare trade values in the same currency.
    frame["insider_activity"] = insider["inr"] if insider.loc[members, "inr"].notna().any() else insider["usd"]
    frame["short_interest"] = latest(
        "short_interest", ["ticker", "short_pct_float"], "settlement_date"
    ).set_index("ticker")["short_pct_float"]
    short_sales = _frame(
        conn,
        """WITH recent_reports AS (
            SELECT trade_date, MAX(known_date) AS known_date FROM nse_short_selling
            WHERE known_date <= ? AND trade_date BETWEEN ? AND ?
            GROUP BY trade_date
            ORDER BY trade_date DESC LIMIT 120
        )
        SELECT ticker, CAST(SUM(short_quantity) AS DOUBLE PRECISION)
                       / NULLIF(SUM(traded_quantity), 0)
        FROM nse_short_selling JOIN recent_reports USING (trade_date, known_date)
        WHERE (SELECT MAX(trade_date) FROM recent_reports) >= ?
        GROUP BY ticker""",
        [asof, asof - timedelta(days=240), asof, asof - timedelta(days=7)],
        ["ticker", "activity"],
    )
    frame["nse_short_selling_activity"] = short_sales.set_index("ticker")["activity"]
    frame["social_buzz"] = latest("social_daily", ["ticker", "mentions"]).set_index("ticker")[
        "mentions"
    ]
    surprise = latest("earnings_surprise", ["ticker", "surprise_pct"], "report_date").set_index(
        "ticker"
    )
    frame["eps_surprise"] = surprise["surprise_pct"] / 100
    if "ret_20d" in frame:
        sector_returns = frame.loc[members].groupby("sector")["ret_20d"].mean()
        frame["hot_sector"] = frame["sector"].map(sector_returns)
    frame.attrs["protected"] = protected
    if comparison_subject:
        frame.attrs["comparison_subject"] = comparison_subject
    return frame, None if bars.empty else bars.date.max()
