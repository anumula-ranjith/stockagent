from datetime import date

from stock_agents.engine.combiner import rank_scores


def test_explicit_weights_change_ranking_and_are_normalized():
    rows = [
        ("TECH", "technical", 90.0),
        ("TECH", "momentum", 10.0),
        ("MOM", "technical", 10.0),
        ("MOM", "momentum", 90.0),
    ]
    result = rank_scores(
        rows, [], date(2025, 2, 3), 1, "weighted",
        custom_weights={"technical": 80, "momentum": 20, "sentiment": 0, "fundamental": 0},
    )
    assert result["longs"][0]["ticker"] == "TECH"
    assert result["longs"][0]["composite"] == 74.0
    assert result["weights"]["technical"] == 0.8
