from __future__ import annotations

import asyncio

import pytest

from app.services.conversion import RenderGate
from app.services.errors import ConversionBusyError, QueueFullError


async def test_gate_rejects_second_job_from_same_user() -> None:
    gate = RenderGate(concurrent=1, queue_size=1)

    async with gate.acquire(10):
        with pytest.raises(ConversionBusyError):
            async with gate.acquire(10):
                pytest.fail("duplicate job entered the gate")


async def test_gate_rejects_jobs_above_total_capacity() -> None:
    gate = RenderGate(concurrent=1, queue_size=0)

    async with gate.acquire(1):
        with pytest.raises(QueueFullError):
            async with gate.acquire(2):
                pytest.fail("overflow job entered the gate")


async def test_gate_waits_and_releases_next_user() -> None:
    gate = RenderGate(concurrent=1, queue_size=1)
    entered = asyncio.Event()

    async def second() -> None:
        async with gate.acquire(2):
            entered.set()

    async with gate.acquire(1):
        task = asyncio.create_task(second())
        await asyncio.sleep(0)
        assert not entered.is_set()
    await task
    assert entered.is_set()
