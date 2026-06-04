"""Progress events emitted by the orchestrator.

Each stage publishes a `ProgressEvent`. The API can stream these to
the UI via SSE; tests just collect them in a list.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class ProgressEvent:
    batch_id: UUID
    stage: int
    name: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ProgressBus:
    """An in-memory pub-sub for ProgressEvents. One per batch."""

    def __init__(self, batch_id: UUID | None = None) -> None:
        self.batch_id = batch_id or uuid4()
        self._subs: list[asyncio.Queue[ProgressEvent | None]] = []
        self._history: list[ProgressEvent] = []

    async def publish(self, stage: int, name: str, detail: str = "", **extra: Any) -> None:
        evt = ProgressEvent(
            batch_id=self.batch_id, stage=stage, name=name, detail=detail, extra=extra
        )
        self._history.append(evt)
        for q in list(self._subs):
            await q.put(evt)

    async def close(self) -> None:
        for q in list(self._subs):
            await q.put(None)
        self._subs.clear()

    @property
    def history(self) -> list[ProgressEvent]:
        return list(self._history)

    def subscribe(self) -> AsyncIterator[ProgressEvent]:
        q: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        for past in self._history:
            q.put_nowait(past)
        self._subs.append(q)

        async def gen() -> AsyncIterator[ProgressEvent]:
            while True:
                evt = await q.get()
                if evt is None:
                    return
                yield evt

        return gen()


# Convenience for callers that don't need streaming.
async def collect(events: Iterable[ProgressEvent]) -> list[str]:
    return [f"[{e.stage:02d}] {e.name}: {e.detail}" for e in events]


_NoopSink: Callable[[ProgressEvent], None] = lambda e: None  # noqa: E731
