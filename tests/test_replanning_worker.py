"""Unit tests for opt-in replanning worker bounds and scope requirements."""
from unittest.mock import patch

import pytest

from app.services.replanning_worker import run_batch


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 101])
async def test_worker_rejects_unbounded_batch(limit):
    with pytest.raises(ValueError, match="limit"):
        await run_batch(limit)


@pytest.mark.asyncio
async def test_worker_process_one_skips_missing_event():
    from app.services.replanning_worker import process_one

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, statement):
            return None

    with patch("app.services.replanning_worker.AsyncSessionLocal", return_value=FakeSession()):
        assert await process_one("not-found") == "skipped"
