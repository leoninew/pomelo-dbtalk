"""Verify that the template executes async Pytest tests in auto mode."""

import asyncio


async def test_asyncio_support_is_enabled() -> None:
    await asyncio.sleep(0)
