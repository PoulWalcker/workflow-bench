#!/bin/sh
set -eu
cat > /app/run.py <<'PY'
import asyncio
from typing import Awaitable, Callable


async def _task_with_semaphore(
    semaphore: asyncio.Semaphore, task: Callable[[], Awaitable[None]]
) -> None:
    async with semaphore:
        await task()


async def run_tasks(
    tasks: list[Callable[[], Awaitable[None]]], max_concurrent: int
) -> None:
    """Run at most max_concurrent tasks and await their cleanup on cancellation."""
    semaphore = asyncio.Semaphore(max_concurrent)
    async with asyncio.TaskGroup() as group:
        for task in tasks:
            group.create_task(_task_with_semaphore(semaphore, task))
PY
