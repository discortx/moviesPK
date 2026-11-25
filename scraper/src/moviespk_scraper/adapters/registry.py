"""Adapter registry (plan §10.1, P1-03).

Every adapter id that ``cinemas.yml`` may use is declared here with its fetch mode. An
adapter that is planned but not built yet has no factory: cinemas using it load fine but
must stay ``enabled: false`` (config validation enforces this). Implementations register
themselves with :func:`register`.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from .base import CinemaAdapter, FetchMode

AdapterFactory = Callable[[], CinemaAdapter]


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    fetch_mode: FetchMode
    factory: AdapterFactory | None = None  # None = declared, not implemented yet

    @property
    def implemented(self) -> bool:
        return self.factory is not None


class UnknownAdapterError(KeyError):
    pass


class AdapterNotImplementedError(RuntimeError):
    pass


def _lazy(module: str, cls: str) -> AdapterFactory:
    """Import the adapter only when it is needed (keeps the registry free of cycles)."""

    def factory() -> CinemaAdapter:
        adapter_cls = getattr(importlib.import_module(module, __package__), cls)
        return cast(CinemaAdapter, adapter_cls())

    return factory


_ADAPTERS: dict[str, AdapterSpec] = {
    # Group A: Cinepax public JSON (docs/cinema-investigation/cinepax.md). P1-06.
    "cinepax": AdapterSpec("cinepax", "json", _lazy(".cinepax", "CinepaxAdapter")),
    # Group B: Vista HTML: Universal, CineStar (docs/cinema-investigation/vista.md). P2-01.
    "vista": AdapterSpec("vista", "html"),
}


def specs() -> dict[str, AdapterSpec]:
    return dict(_ADAPTERS)


def spec(adapter_id: str) -> AdapterSpec:
    try:
        return _ADAPTERS[adapter_id]
    except KeyError:
        raise UnknownAdapterError(adapter_id) from None


def register(adapter_id: str, fetch_mode: FetchMode, factory: AdapterFactory) -> None:
    """Attach an implementation to a declared (or new) adapter id."""
    existing = _ADAPTERS.get(adapter_id)
    if existing is not None and existing.fetch_mode != fetch_mode:
        raise ValueError(
            f"adapter {adapter_id!r} is declared as {existing.fetch_mode}, not {fetch_mode}"
        )
    _ADAPTERS[adapter_id] = AdapterSpec(adapter_id, fetch_mode, factory)


def get_adapter(adapter_id: str) -> CinemaAdapter:
    entry = spec(adapter_id)
    if entry.factory is None:
        raise AdapterNotImplementedError(f"adapter {adapter_id!r} is not implemented yet")
    return entry.factory()
