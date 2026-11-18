import pandas as pd

from stock_agents.common.config import project_root


def test_seed_has_213_rows_and_no_duplicates():
    df = pd.read_csv(project_root() / "config" / "universe_seed.csv", comment="#")
    assert len(df) == 213
    assert df["ticker"].is_unique
    assert df["ticker"].notna().all()
    assert df["sector"].notna().all()


def test_seed_covers_expected_sectors():
    df = pd.read_csv(project_root() / "config" / "universe_seed.csv", comment="#")
    sectors = set(df["sector"])
    for s in (
        "Information Technology",
        "Health Care",
        "Financials",
        "Consumer Staples",
        "Energy",
    ):
        assert s in sectors, f"seed missing sector {s}"
