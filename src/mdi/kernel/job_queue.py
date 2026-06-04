"""Celery + Redis wiring.

Long-running batches go through this queue; the API returns immediately
with a batch_id and the Streamlit UI polls (or a webhook fires) on
completion. Phase 2+ wires real handlers; for Phase 1 we keep the
infrastructure and a single placeholder task so the import works.
"""
from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery

from mdi.kernel.settings import get_settings

_celery_app: Celery | None = None


def get_celery() -> Celery:
    global _celery_app
    if _celery_app is None:
        s = get_settings()
        _celery_app = Celery(
            "mdi",
            broker=s.celery_broker_url,
            backend=s.celery_result_backend,
        )
        _celery_app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            task_track_started=True,
            task_time_limit=s.batch_timeout_seconds,
            worker_prefetch_multiplier=1,
            broker_connection_retry_on_startup=True,
        )
    return _celery_app


# Register tasks at import time. The orchestrator imports this module which
# triggers task registration on the celery app.
celery_app = get_celery()


@celery_app.task(name="mdi.run_batch")
def run_batch(tenant_id: str, document_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase-1 placeholder. Real wiring in Phase 4 calls
    `mdi.orchestrator.pipeline.run` and returns the BatchReport JSON."""
    from mdi.orchestrator.pipeline import run_batch_async

    return asyncio.run(run_batch_async(tenant_id=tenant_id, payloads=document_payloads))
