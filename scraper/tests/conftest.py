from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """``configure_logging`` changes structlog globally (for example to a captured stream
    that pytest closes after the test); restore the defaults after every test."""
    yield
    structlog.reset_defaults()
