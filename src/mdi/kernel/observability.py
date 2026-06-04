"""Observability — structlog + optional Langfuse.

Langfuse is a no-op when keys are absent so tests run fully offline.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from mdi.kernel.settings import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Langfuse — optional. Falls back to a no-op shim when keys are absent.
# ---------------------------------------------------------------------------
class _NoopTrace:
    def update(self, **kwargs: Any) -> None: ...
    def end(self, **kwargs: Any) -> None: ...


class _NoopLangfuse:
    def trace(self, **kwargs: Any) -> _NoopTrace:
        return _NoopTrace()

    def generation(self, **kwargs: Any) -> _NoopTrace:
        return _NoopTrace()

    def flush(self) -> None: ...


def get_langfuse() -> Any:
    """Return a real Langfuse client if keys are set, else a no-op shim."""
    s = get_settings()
    if not s.langfuse_public_key or not s.langfuse_secret_key:
        return _NoopLangfuse()
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]

        return Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
    except Exception:  # pragma: no cover — graceful degradation
        return _NoopLangfuse()
