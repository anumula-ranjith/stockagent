"""FactSet Formula cross-sectional snapshots keyed by the exchange-published ISIN."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import requests

# Formula returns margins and debt/equity in percentage points. Convert once
# at the warehouse boundary. Market values and free cash flow are INR millions.
FORMULAS = {
    "net_margin_ttm": ("FF_NET_MGN(LTM,0)", 0.01),
    "operating_margin_ttm": ("FF_OPER_MGN(LTM,0)", 0.01),
    "gross_margin": ("FF_GROSS_MGN(LTM,0)", 0.01),
    "roic": ("FF_ROIC(ANN,0)", 0.01),
    "current_ratio": ("FF_CURR_RATIO(QTR,0)", 1),
    "debt_equity": ("FF_DEBT_EQ(QTR,0)", 0.01),
    "interest_coverage": ("FF_INT_COVG(LTM,0)", 1),
    "eps_ttm": ("FF_EPS(LTM,0,0,INR)", 1),
    "market_cap": ("P_MARKET_VALUE(0,INR)", 1_000_000),
    "_fcf": ("FF_FREE_CF(LTM,0,0,INR)", 1_000_000),
    "_annual_fcf": ("FF_FREE_CF(ANN,0,0,INR)", 1_000_000),
    "_annual_repurchases": ("FF_STK_PURCH_CF(ANN,0,0,INR)", 1_000_000),
    "_annual_issuance": ("FF_STK_SALE_CF(ANN,0,0,INR)", 1_000_000),
    "_price": ("P_PRICE(0,INR)", 1),
    "eps_fy1": ("FE_ESTIMATE(EPS,MEAN,ANN,+1,0,INR)", 1),
    "eps_fy2": ("FE_ESTIMATE(EPS,MEAN,ANN,+2,0,INR)", 1),
    "rating_mean": ("FE_RATING(MEAN)", 1),
    "_previous_rating": ("FE_RATING(MEAN,NOTE,-1M)", 1),
    "target_mean": ("FE_ESTIMATE(PRICE_TGT,MEAN,0)", 1),
}


@dataclass
class FactSetClient:
    username: str = field(repr=False)
    api_key: str = field(repr=False)
    endpoint: str

    @classmethod
    def from_env(cls) -> FactSetClient:
        user, key = os.getenv("FACTSET_USERNAME_SERIAL"), os.getenv("FACTSET_API_KEY")
        if not user or not key:
            raise RuntimeError("FactSet Formula credentials are missing")
        base = os.getenv("FACTSET_BASE_URL") or "https://api.factset.com/formula-api/v1/time-series"
        base = base.rstrip("/").removesuffix("/time-series").removesuffix("/cross-sectional")
        return cls(user, key, base + "/cross-sectional")

    def _columns(self, isins, formulas, *, fsym_id=False):
        response = requests.post(
            self.endpoint,
            auth=(self.username, self.api_key),
            timeout=(10, 60),
            json={
                "data": {
                    "ids": isins,
                    "formulas": formulas,
                    "flatten": "N",
                    "fsymId": "Y" if fsym_id else "N",
                }
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"FactSet Formula HTTP {response.status_code}")
        columns = {v["dataItemName"]: v for v in response.json()["data"]}
        ids = columns["requestId"]["result"]
        if len(ids) != len(isins) or set(ids) != set(isins):
            raise ValueError("FactSet identifier set differs from the request")
        return ids, columns

    def regional_ids(self, isins):
        ids, columns = self._columns(isins, ["P_NAME"], fsym_id=True)
        return dict(zip(ids, columns["fsymId"]["result"], strict=True))

    def snapshot(self, isins: list[str]) -> dict[str, dict]:
        from stock_agents.ingest.provider_values import number, ratio

        ids, columns = self._columns(isins, ["P_CURRENCY", *(f for f, _ in FORMULAS.values())])
        currencies = dict(zip(ids, columns["P_CURRENCY"]["result"], strict=True))
        output: dict[str, dict] = {i: {} for i in ids}
        for metric, (formula, scale) in FORMULAS.items():
            column = columns[formula]
            if column.get("error") or len(column["result"]) != len(ids):
                raise ValueError(f"FactSet Formula returned an invalid column for {metric}")
            for isin, raw in zip(ids, column["result"], strict=True):
                value = number(raw)
                if value is not None:
                    output[isin][metric] = value * scale
        for isin, values in output.items():
            if currencies[isin] != "Indian Rupee":
                # Regional identities must resolve to rupee-denominated listings.
                values.clear()
                continue
            price = values.pop("_price", None)
            cap = values.get("market_cap")
            previous = values.pop("_previous_rating", None)
            if previous is not None and "rating_mean" in values:
                values["rating_change_1m"] = previous - values["rating_mean"]
            repurchased = values.pop("_annual_repurchases", None)
            issued = values.pop("_annual_issuance", None)
            if repurchased is not None and issued is not None:
                values["buyback_yield"] = ratio(repurchased - issued, cap)
            values.update(
                pe_ttm=ratio(price, values.get("eps_ttm")),
                forward_pe=ratio(price, values.get("eps_fy1")),
                fcf_yield=ratio(values.pop("_fcf", None), cap),
                fcf_yield_fy=ratio(values.pop("_annual_fcf", None), cap),
            )
        return output
