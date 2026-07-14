import asyncio
from dataclasses import dataclass


class QuotaExceeded(Exception):
    pass


@dataclass
class ResourceQuota:
    max_steps: int = 0
    max_tokens: int = 0


@dataclass
class Usage:
    steps: int = 0
    tokens: int = 0


class Account:
    """累计资源消耗,超限拒绝。asyncio.Lock 保护(协程安全)。"""

    def __init__(self, quota: ResourceQuota):
        self._mu = asyncio.Lock()
        self.quota = quota
        self._used = Usage()

    async def charge(self, u: Usage) -> None:
        """扣减资源。任一项超限抛 QuotaExceeded(但已累加,调用方应终止)。"""
        async with self._mu:
            self._used.steps += u.steps
            self._used.tokens += u.tokens
            if self.quota.max_steps > 0 and self._used.steps > self.quota.max_steps:
                raise QuotaExceeded()
            if self.quota.max_tokens > 0 and self._used.tokens > self.quota.max_tokens:
                raise QuotaExceeded()

    async def used(self) -> Usage:
        async with self._mu:
            return Usage(steps=self._used.steps, tokens=self._used.tokens)
