"""RemoteSandboxExecutor:沙箱经消息总线请求-响应。

publish 到 actions.{sid},await observations 的响应(correlation_id 匹配)。
约束5/7 端到端:控制面不经 sandbox.exec_action 直调,经总线交付沙箱执行面。
"""
import asyncio
import uuid
from typing import Any, Dict


class RemoteSandboxExecutor:
    """SandboxPort 实现:把 create/exec_action/destroy 翻译成总线消息。

    请求 topic: actions.{sandbox_id}
    响应 topic: observations (字段 correlation_id 匹配请求)
    """

    def __init__(self, bus, timeout: float = 30.0):
        self._bus = bus
        self._timeout = timeout
        self._pending: Dict[str, asyncio.Future] = {}
        self._started = False

    def _ensure_started(self) -> None:
        """惰性订阅 observations(只订一次)。"""
        if self._started:
            return
        self._bus.subscribe("observations", self._on_observation)
        self._started = True

    async def _on_observation(self, msg: Dict[str, Any]) -> None:
        corr = msg.get("correlation_id")
        if corr and corr in self._pending:
            fut = self._pending.pop(corr)
            if not fut.done():
                fut.set_result(msg.get("result", {}))

    async def create(self, config: Dict[str, Any]) -> str:
        sid = f"sbx-remote-{uuid.uuid4().hex[:8]}"
        await self._bus.publish(f"actions.{sid}", {"op": "create", "config": config})
        return sid

    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_started()
        corr = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[corr] = fut
        await self._bus.publish(f"actions.{sandbox_id}",
                                {"op": "exec", "action": action, "correlation_id": corr})
        try:
            return await asyncio.wait_for(fut, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._pending.pop(corr, None)
            return {"error": "sandbox timeout"}

    async def destroy(self, sandbox_id: str) -> None:
        await self._bus.publish(f"actions.{sandbox_id}", {"op": "destroy"})
