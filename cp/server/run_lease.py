"""Run 执行租约(Redis 分布式锁)。SET run:{id}:lease {replica_id} NX EX ttl。

持租约的副本能执行 run;过期或释放后其他副本能接管。
实现 ch15 约束6(跨副本)+ run 执行互斥。"""
import uuid
from typing import Optional


class RedisRunLease:
    def __init__(self, redis, ttl: int = 30):
        self._r = redis
        self._ttl = ttl
        self._replica_id = f"replica-{uuid.uuid4().hex[:8]}"

    @property
    def replica_id(self) -> str:
        return self._replica_id

    async def acquire(self, run_id: str) -> bool:
        """尝试获取 run 的执行租约。成功返回 True,已被持有返回 False。"""
        key = f"run:{run_id}:lease"
        result = await self._r.set(key, self._replica_id, nx=True, ex=self._ttl)
        return bool(result)

    async def renew(self, run_id: str) -> bool:
        """续租(只有持有者能续)。成功返回 True。"""
        key = f"run:{run_id}:lease"
        current = await self._r.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == self._replica_id:
            await self._r.expire(key, self._ttl)
            return True
        return False

    async def release(self, run_id: str) -> None:
        """释放租约(只有持有者能释放)。"""
        key = f"run:{run_id}:lease"
        current = await self._r.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == self._replica_id:
            await self._r.delete(key)

    async def holder(self, run_id: str) -> Optional[str]:
        """当前持有者的 replica_id(或 None)。"""
        key = f"run:{run_id}:lease"
        raw = await self._r.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw
