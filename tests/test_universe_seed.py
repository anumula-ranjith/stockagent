import pandas as pd

from stock_agents.common.config import project_root


def test_seed_has_100_rows_and_no_duplicates():
    df = pd.read_csv(project_root() / "config" / "universe_seed.csv")
    assert len(df) == 100, f"expected 100 tickers, got {len(df)}"
    assert df["ticker"].is_unique
    assert df["ticker"].notna().all()
    assert df["sector"].notna().all()


def test_seed_covers_expected_sectors():
    df = pd.read_csv(project_root() / "config" / "universe_seed.csv")
    sectors = set(df["sector"])
    for s in (
        "Technology",
        "Health Care",
        "Financials",
        "Consumer Staples",
        "Energy",
    ):
        assert s in sectors, f"seed missing sector {s}"
