import json
from typing import Any, Dict, Optional


class RedisStatePort:
    """StatePort 的 Redis 实现。session 状态存 Redis KV(ch15 约束3)。
    开发用 fakeredis,生产连真实 Redis——接口不变。"""

    def __init__(self, redis):
        self._r = redis

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._r.get(f"session:{session_id}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    async def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        await self._r.set(f"session:{session_id}", json.dumps(state))

    async def delete_session(self, session_id: str) -> None:
        await self._r.delete(f"session:{session_id}")
