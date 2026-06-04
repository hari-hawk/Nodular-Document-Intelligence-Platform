"""pytest fixtures shared across the suite."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

# Make `tests/` importable as a package alongside `src/mdi/`.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

# Force tests offline by default.
os.environ.setdefault("GOOGLE_API_KEY", "")
os.environ.setdefault("DAILY_SPEND_CAP_USD", "100")


@pytest.fixture
def fake_gateway():
    from tests.fake_gateway import FakeGateway

    return FakeGateway()


@pytest.fixture
def installed_fake_gateway(fake_gateway):
    """Install the FakeGateway as the process-wide singleton for the duration of the test."""
    from mdi.kernel.llm_gateway import reset_gateway, set_gateway

    set_gateway(fake_gateway)
    try:
        yield fake_gateway
    finally:
        reset_gateway()


@pytest.fixture
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
