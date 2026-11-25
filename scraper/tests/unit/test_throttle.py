"""HostThrottle: one request in flight per host, across threads (max_concurrency: 1)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from moviespk_scraper.core.throttle import HostThrottle


def test_one_request_in_flight_per_host_across_threads() -> None:
    throttle = HostThrottle()
    active = 0
    peak = 0
    lock = threading.Lock()

    def work(host: str) -> None:
        nonlocal active, peak
        with throttle.slot(host, delay_ms=0):
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(work, ["https://same.example"] * 6))
    assert peak == 1


def test_different_hosts_run_in_parallel() -> None:
    throttle = HostThrottle()
    barrier = threading.Barrier(2, timeout=2)

    def work(host: str) -> None:
        with throttle.slot(host, delay_ms=0):
            barrier.wait()  # deadlocks (BrokenBarrierError) if hosts were serialized

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work, ["https://a.example", "https://b.example"]))
