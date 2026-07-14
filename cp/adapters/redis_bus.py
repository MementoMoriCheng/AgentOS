import asyncio
import json
from typing import Any, Callable, Dict, List


class RedisStreamMessageBus:
    """MessageBusPort 的 Redis Stream 实现。XADD 发布,XREAD 消费分发。
    事件持久化在 Stream(可 replay)。开发用 fakeredis,生产连真实 Redis——接口不变。"""

    def __init__(self, redis):
        self._r = redis
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._task = None
        self._stop = False
        self._last_ids: Dict[str, str] = {}

    def subscribe(self, topic: str, handler: Callable) -> Callable[[], None]:
        self._subscriptions.setdefault(topic, []).append(handler)
        self._last_ids.setdefault(topic, "0")  # 从头消费(replay 能力)
        def _unsub():
            if handler in self._subscriptions.get(topic, []):
                self._subscriptions[topic].remove(handler)
        return _unsub

    async def publish(self, topic: str, message: Dict[str, Any]) -> None:
        await self._r.xadd(topic, {"data": json.dumps(message)})

    async def start(self) -> None:
        self._stop = False
        self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _consume(self) -> None:
        while not self._stop:
            if not self._subscriptions:
                await asyncio.sleep(0.01)
                continue
            streams = {t: self._last_ids[t] for t in self._subscriptions}
            try:
                results = await self._r.xread(streams, count=10, block=50)
            except asyncio.CancelledError:
                break
            for topic, entries in results:
                topic_key = topic.decode() if isinstance(topic, bytes) else topic
                for entry_id, fields in entries:
                    self._last_ids[topic_key] = (
                        entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                    )
                    raw = fields.get(b"data") or fields.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    data = json.loads(raw)
                    for h in list(self._subscriptions.get(topic_key, [])):
                        try:
                            await h(data)
                        except Exception:
                            pass
