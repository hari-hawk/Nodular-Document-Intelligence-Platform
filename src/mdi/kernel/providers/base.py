"""Base provider contract + tiny registry."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Callable


class ProviderError(RuntimeError):
    """Generic provider failure (auth, network, schema)."""


class ProviderNotConfigured(ProviderError):
    """Raised when an env-configured key is missing."""


@dataclass
class ProviderCallResult:
    text: str
    raw: Any
    input_tokens: int
    output_tokens: int


class BaseProvider(abc.ABC):
    """Capability flags help the router pick the right provider per organ."""

    name: str = "abstract"
    supports_vision: bool = False
    supports_json_mode: bool = False
    supports_tools: bool = False

    @abc.abstractmethod
    async def call(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None,
        images: list[bytes],
        json_mode: bool,
        max_output_tokens: int | None,
        temperature: float,
    ) -> ProviderCallResult:
        ...

    @abc.abstractmethod
    def retryable_exceptions(self) -> tuple[type[BaseException], ...]:
        ...


# ---------------------------------------------------------------------------
# Tiny registry — providers self-register at import time.
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, Callable[[], BaseProvider]] = {}
_INSTANCES: dict[str, BaseProvider] = {}


def register_provider(name: str, factory: Callable[[], BaseProvider]) -> None:
    _REGISTRY[name] = factory


def get_provider(name: str) -> BaseProvider:
    if name not in _INSTANCES:
        if name not in _REGISTRY:
            raise ProviderError(f"unknown provider: {name!r}")
        _INSTANCES[name] = _REGISTRY[name]()
    return _INSTANCES[name]


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


def reset_providers() -> None:
    """Drop cached instances — used by tests."""
    _INSTANCES.clear()
