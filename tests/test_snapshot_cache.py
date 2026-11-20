from threading import Event

import pytest

from stock_agents.common.snapshot_cache import SnapshotCache


def test_refresh_serves_previous_snapshot_without_waiting():
    cache = SnapshotCache(ttl=0)
    gate = Event()
    started = Event()
    try:
        assert cache.get("day", lambda: 1) == 1
        def refresh():
            started.set()
            assert gate.wait(2)
            return 2
        assert cache.get("day", refresh) == 1
        assert started.wait(1)
        assert cache.get("day", lambda: pytest.fail("Duplicate refresh")) == 1
        gate.set()
    finally:
        gate.set()
        cache.pool.shutdown(wait=True)
    assert cache.entries["day"][1] == 2


def test_failed_refresh_does_not_replace_good_snapshot_or_serve_expired_data():
    cache = SnapshotCache(ttl=0, max_age=0)
    try:
        assert cache.get("day", lambda: 1) == 1
        def fail():
            raise ValueError("Source unavailable")
        with pytest.raises(ValueError):
            cache.get("day", fail)
        assert cache.entries["day"][1] == 1
    finally:
        cache.pool.shutdown(wait=True)
