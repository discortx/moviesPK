"""P1-11: the zero-result and median guards (plan §8.4)."""

from __future__ import annotations

import pytest

from moviespk_scraper.pipeline.reconcile import guard_reason


@pytest.mark.parametrize(
    ("count", "history", "fails"),
    [
        (0, [], True),  # zero result always fails
        (0, [19, 19, 19], True),
        (5, [], False),  # no history: warm-up
        (5, [19, 19], False),  # 2 ok runs: still warming up
        (9, [19, 19, 19], True),  # 9 < 9.5
        (10, [19, 19, 19], False),  # 10 >= 9.5
        (6, [20, 4, 30, 22, 18, 25, 19, 999, 999], True),  # median of the latest 7 = 20
        (12, [20, 4, 30, 22, 18, 25, 19, 999, 999], False),
    ],
)
def test_guard(count: int, history: list[int], fails: bool) -> None:
    assert (guard_reason(count, history) is not None) is fails


def test_messages_explain_the_guard() -> None:
    assert "zero result" in (guard_reason(0, []) or "")
    assert "median" in (guard_reason(1, [19, 19, 19]) or "")
