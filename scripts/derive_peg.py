"""Store PEG calculated from observed EODHD P/E and FY1 EPS estimates."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.jobs.queue import sync_engine
from stock_agents.storage.postgres import Base


def derive_peg(observed: date | None = None) -> dict[str, int]:
    load_settings()
    observed = observed or __import__("datetime").datetime.now(ZoneInfo("Asia/Kolkata")).date()
    query = text("""
        WITH latest AS (
          SELECT ticker, metric, value,
                 ROW_NUMBER() OVER (PARTITION BY ticker,metric ORDER BY effective_date DESC,known_date DESC) rn
          FROM fundamentals_pit
          WHERE source='eodhd' AND metric IN ('pe_ttm','eps_ttm','peg')
            AND effective_date<=:day AND known_date<=:day
        ), estimates AS (
          SELECT ticker, value,
                 ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC,known_date DESC) rn
          FROM estimates_pit
          WHERE source='eodhd' AND metric='eps_fy1'
            AND effective_date<=:day AND known_date<=:day
        )
        SELECT pe.ticker,pe.value,eps.value,est.value
        FROM latest pe JOIN latest eps ON pe.ticker=eps.ticker AND eps.metric='eps_ttm' AND eps.rn=1
        JOIN estimates est ON est.ticker=pe.ticker AND est.rn=1
        LEFT JOIN latest reported ON reported.ticker=pe.ticker AND reported.metric='peg' AND reported.rn=1
        WHERE pe.metric='pe_ttm' AND pe.rn=1 AND reported.ticker IS NULL
          AND NOT EXISTS (SELECT 1 FROM fundamentals_pit existing
            WHERE existing.ticker=pe.ticker AND existing.metric='peg'
              AND existing.source='eodhd_derived' AND existing.effective_date=:day)
    """)
    rows = []
    with sync_engine().begin() as connection:
        candidates = connection.execute(query, {"day": observed}).all()
        for ticker, pe, eps, future_eps in candidates:
            if not pe or pe <= 0 or not eps or eps <= 0 or future_eps is None:
                continue
            growth_percent = (future_eps / eps - 1) * 100
            if growth_percent <= 0:
                continue
            peg = pe / growth_percent
            if not 0 < peg < 1000:
                continue
            rows.append(dict(ticker=ticker, metric="peg", fiscal_period=f"snapshot:{observed}",
                             value=peg, effective_date=observed, known_date=observed,
                             source="eodhd_derived"))
        if rows:
            connection.execute(insert(Base.metadata.tables["fundamentals_pit"]).values(rows)
                               .on_conflict_do_nothing())
    return {"candidates": len(candidates), "derived": len(rows)}


if __name__ == "__main__":
    print(derive_peg())
