"""Shared point-in-time stock selection for dashboard rankings and portfolio replays."""

from typing import Literal

from pydantic import BaseModel

from stock_agents.ingest.screen_indices import CAP_INDEX, INDEX_FILES


class UniverseSelection(BaseModel):
    index_code: str = "NIFTY500"
    cap: Literal["", "large", "mid", "small"] = ""
    industry: str = ""
    fo_only: bool = False

    def eligible(self, tickers, groups, industries):
        names = set(tickers)
        codes = [self.index_code] if self.index_code != "NIFTY500" else []
        if self.cap:
            codes.append(CAP_INDEX[self.cap])
        if self.fo_only:
            codes.append("NSE_FO")
        for code in codes:
            names.intersection_update(groups.get(code, ()))
        if self.industry:
            names = {name for name in names if industries.get(name) == self.industry}
        return names


def universe_metadata(conn, asof):
    memberships = conn.execute(
        """SELECT index_code,ticker FROM index_membership
           WHERE known_on <= ? AND joined_on <= ? AND (left_on IS NULL OR left_on > ?)
           AND index_code = ANY(?)""",
        [asof, asof, asof, [*INDEX_FILES, "NSE_FO"]],
    ).fetchall()
    industries = dict(conn.execute(
        """SELECT DISTINCT ON (ticker) ticker,industry FROM classification
           WHERE source='nse_indices' AND known_date <= ? AND effective_date <= ?
             AND NULLIF(TRIM(industry),'') IS NOT NULL
           ORDER BY ticker,effective_date DESC,known_date DESC""", [asof, asof],
    ).fetchall())
    groups = {}
    for code, ticker in memberships:
        groups.setdefault(code, set()).add(ticker)
    return groups, industries

