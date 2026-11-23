"""进程内手机聊天流 broker。

按入站 event id 聚合 LLM 的累计文本，供 SSE 端点订阅：
- 晚订阅先收到当前快照，再收到后续增量；
- 处理完成/失败后保留终态一段时间，支持“处理完成后才连上”的客户端；
- 仅单进程有效：多 worker/副本时订阅可能拿不到状态，客户端回退轮询。

文本回调语义是「本次模型调用的累计文本」，不是增量；客户端按覆盖渲染。
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field

MAX_TEXT_CHARS = 20000
DEFAULT_TTL_SECONDS = 600.0
DEFAULT_MAX_STREAMS = 200

StreamMessage = tuple[str, dict]


@dataclass
class _Stream:
    text: str = ""
    done: bool = False
    error: str | None = None
    reply_id: str | None = None
    occurred_at: str | None = None
    updated_at: float = field(default_factory=time.monotonic)
    queues: set[asyncio.Queue[StreamMessage]] = field(default_factory=set)


class ChatStreamBroker:
    """单进程内的聊天流注册表。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_streams: int = DEFAULT_MAX_STREAMS,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_streams = max_streams
        self._streams: dict[uuid.UUID, _Stream] = {}

    def open(self, event_id: uuid.UUID) -> None:
        """在开始处理时创建空流，保证早到的订阅能等待首个增量。"""
        self._get_or_create(event_id)

    def has(self, event_id: uuid.UUID) -> bool:
        self._prune()
        return event_id in self._streams

    def publish(self, event_id: uuid.UUID, text: str) -> None:
        """发布本次模型调用的累计文本。"""
        stream = self._get_or_create(event_id)
        if stream.done or stream.error is not None:
            return
        stream.text = text[:MAX_TEXT_CHARS]
        stream.updated_at = time.monotonic()
        self._broadcast(stream, ("delta", {"text": stream.text}))

    def finish(
        self,
        event_id: uuid.UUID,
        *,
        text: str,
        reply_id: str | None,
        occurred_at: str | None,
    ) -> None:
        stream = self._get_or_create(event_id)
        stream.text = text[:MAX_TEXT_CHARS]
        stream.reply_id = reply_id
        stream.occurred_at = occurred_at
        stream.done = True
        stream.updated_at = time.monotonic()
        self._broadcast(stream, ("done", self._done_payload(stream, event_id)))

    def fail(self, event_id: uuid.UUID, code: str = "processing_failed") -> None:
        stream = self._get_or_create(event_id)
        stream.error = code
        stream.done = True
        stream.updated_at = time.monotonic()
        self._broadcast(stream, ("error", {"code": code}))

    def attach(
        self, event_id: uuid.UUID
    ) -> tuple[asyncio.Queue[StreamMessage], list[StreamMessage]] | None:
        """订阅流；返回 (队列, 初始事件)。流不存在时返回 None。"""
        self._prune()
        stream = self._streams.get(event_id)
        if stream is None:
            return None
        if stream.error is not None:
            return asyncio.Queue(), [("error", {"code": stream.error})]
        if stream.done:
            return asyncio.Queue(), [("done", self._done_payload(stream, event_id))]
        queue: asyncio.Queue[StreamMessage] = asyncio.Queue()
        stream.queues.add(queue)
        initial: list[StreamMessage] = []
        if stream.text:
            initial.append(("delta", {"text": stream.text}))
        return queue, initial

    def detach(self, event_id: uuid.UUID, queue: asyncio.Queue[StreamMessage]) -> None:
        stream = self._streams.get(event_id)
        if stream is not None:
            stream.queues.discard(queue)

    def _done_payload(self, stream: _Stream, event_id: uuid.UUID) -> dict:
        return {
            "text": stream.text,
            "messageId": stream.reply_id,
            "replyToId": str(event_id),
            "createdAt": stream.occurred_at,
        }

    def _get_or_create(self, event_id: uuid.UUID) -> _Stream:
        self._prune()
        stream = self._streams.get(event_id)
        if stream is not None:
            return stream
        if len(self._streams) >= self._max_streams:
            self._evict_one()
        stream = _Stream()
        self._streams[event_id] = stream
        return stream

    def _broadcast(self, stream: _Stream, message: StreamMessage) -> None:
        for queue in list(stream.queues):
            queue.put_nowait(message)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            event_id
            for event_id, stream in self._streams.items()
            if now - stream.updated_at > self._ttl
        ]
        for event_id in expired:
            self._streams.pop(event_id, None)

    def _evict_one(self) -> None:
        finished = [
            (stream.updated_at, event_id)
            for event_id, stream in self._streams.items()
            if stream.done
        ]
        candidates = finished or [
            (stream.updated_at, event_id) for event_id, stream in self._streams.items()
        ]
        if not candidates:
            return
        _, event_id = min(candidates)
        self._streams.pop(event_id, None)
