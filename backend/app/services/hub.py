"""In-process pub/sub that lets worker threads push messages to WebSockets.

Worker threads call :func:`Hub.publish`; the message is handed to the asyncio
loop with ``call_soon_threadsafe`` and lands in each subscriber's queue.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.utils import to_jsonable


class Hub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(channel, set()).add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(channel)
            if subs:
                subs.discard(queue)
                if not subs:
                    self._subs.pop(channel, None)

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            queues = list(self._subs.get(channel, ()))
        if not queues:
            return
        payload = to_jsonable(message)
        for queue in queues:
            try:
                loop.call_soon_threadsafe(self._put, queue, payload)
            except RuntimeError:  # loop shutting down
                return

    @staticmethod
    def _put(queue: asyncio.Queue, payload: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)


hub = Hub()
