"""后台任务管理：保存引用，避免任务被垃圾回收或异常无人察觉（asyncio 官方模式）。"""

import asyncio
from collections.abc import Coroutine
from logging import Logger

from app.core.logging import get_logger

logger: Logger = get_logger(__name__)

# 模块级引用集合：done 回调自动清理
_background_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine) -> asyncio.Task:
    """把协程放入后台执行并保存引用；异常打印日志，不静默吞掉。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("background task crashed: %s", task.exception(), exc_info=task.exception())
