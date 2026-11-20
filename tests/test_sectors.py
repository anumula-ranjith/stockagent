from stock_agents.ingest.sectors import sector_for


def test_sector_mapping_keeps_observed_sector():
    assert sector_for("Financial Services", "Financials") == "Financials"
    assert sector_for("Healthcare", " ") == "Health Care"
    assert sector_for("Realty") == "Real Estate"


def test_unknown_industries_are_not_guessed():
    assert sector_for("New unclassified industry") is None
    assert sector_for(None) is None
    assert sector_for("Diversified") == "Diversified"
