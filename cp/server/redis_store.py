"""Run 状态的外部存储(Redis)。让约束 6(控制面无状态)在可观测面成立:
任一副本能 list/get/replay 任意 run;WS 实时经 pub/sub channel 跨副本。

存储布局:
  run:{run_id}:meta    → HASH(元数据:run_id/session_id/status/task/...)
  run:{run_id}:events  → LIST(事件序列,可回放)
  run:{run_id}:ch      → pub/sub channel(实时事件推送)
"""
import json
from typing import Any, Dict, List, Optional


class RedisRunStore:
    """Run 元数据 + 事件的外部 Redis 存储。跨副本可观测。"""

    def __init__(self, redis):
        self._r = redis

    def _meta_key(self, run_id: str) -> str:
        return f"run:{run_id}:meta"

    def _events_key(self, run_id: str) -> str:
        return f"run:{run_id}:events"

    def channel(self, run_id: str) -> str:
        """pub/sub channel 名(跨副本实时事件)。"""
        return f"run:{run_id}:ch"

    async def save_meta(self, run_id: str, meta: Dict[str, Any]) -> None:
        """存/更新 run 元数据(HSET,字段值 JSON 序列化)。"""
        await self._r.hset(self._meta_key(run_id),
                           mapping={k: json.dumps(v, default=str) for k, v in meta.items()})

    async def get_meta(self, run_id: str) -> Optional[Dict[str, Any]]:
        """读 run 元数据。无则 None。"""
        raw = await self._r.hgetall(self._meta_key(run_id))
        if not raw:
            return None
        return {self._d(k): json.loads(self._d(v)) for k, v in raw.items()}

    async def append_event(self, run_id: str, event: Dict[str, Any]) -> None:
        """追加事件到 LIST + publish 到 channel(实时)。"""
        payload = json.dumps(event, default=str)
        await self._r.rpush(self._events_key(run_id), payload)
        await self._r.publish(self.channel(run_id), payload)

    async def get_events(self, run_id: str) -> List[Dict[str, Any]]:
        """读全部事件(回放用)。"""
        raw = await self._r.lrange(self._events_key(run_id), 0, -1)
        return [json.loads(self._d(x)) for x in raw]

    async def list_runs(self) -> List[Dict[str, Any]]:
        """列出所有 run 元数据(SCAN run:*:meta)。Week 6 量级足够。"""
        out = []
        async for k in self._r.scan_iter(match="run:*:meta"):
            key = self._d(k)
            run_id = key.split(":")[1]
            meta = await self.get_meta(run_id)
            if meta:
                out.append(meta)
        return out

    @staticmethod
    def _d(v) -> str:
        return v.decode() if isinstance(v, bytes) else v
