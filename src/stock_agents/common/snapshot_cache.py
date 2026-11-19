"""Bounded shared market snapshots with coalesced background refreshes."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from time import monotonic


class SnapshotCache:
    def __init__(self, ttl=120, max_age=600, capacity=32):
        self.ttl, self.max_age, self.capacity = ttl, max_age, capacity
        self.entries = OrderedDict()
        self.pending = {}
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-cache")

    def get(self, key, loader):
        with self.lock:
            entry = self.entries.get(key)
            age = monotonic() - entry[0] if entry else float("inf")
            if entry:
                self.entries.move_to_end(key)
            if age < self.ttl:
                return entry[1]
            future = self.pending.get(key)
            if future is None:
                future = self.pool.submit(loader)
                self.pending[key] = future
                future.add_done_callback(lambda done: self._complete(key, done))
            if entry and age < self.max_age:
                return entry[1]
        result = future.result()
        self._complete(key, future)
        return result

    def invalidate(self):
        with self.lock:
            self.entries.clear()
            self.pending.clear()

    def _complete(self, key, future):
        with self.lock:
            if self.pending.get(key) is not future:
                return
            self.pending.pop(key, None)
            if future.exception() is not None:
                return
            self.entries[key] = (monotonic(), future.result())
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
