from stock_agents.common import config


def test_settings_load(tmp_path):
    s = config.load_settings()
    assert s.timezone == "Asia/Kolkata"
    assert s.market_calendar == "XNSE"
    # The fixture redirects paths to tmp.
    assert s.paths.duckdb.name == "market.duckdb"
    assert s.paths.data_dir.parent == tmp_path
    assert s.paths.data_dir.exists()


def test_weights_have_four_agents():
    s = config.load_settings()
    assert set(s.weights["combiner"]["agent_weights"]) == {
        "technical",
        "sentiment",
        "momentum",
        "fundamental",
    }
    assert sum(s.weights["combiner"]["agent_weights"].values()) == 100


def test_each_agent_block_present():
    s = config.load_settings()
    for name in ("technical", "sentiment", "momentum", "fundamental"):
        assert name in s.weights["agents"], f"missing agent {name}"
        assert s.weights["agents"][name]["enabled"] is True
