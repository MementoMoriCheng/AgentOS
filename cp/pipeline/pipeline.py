from dataclasses import dataclass, field
from typing import Any, Dict

from cp.eventbus.bus import Bus, Event, FieldSanitization
from cp.session.account import QuotaExceeded, Usage
from cp.session.session import Session
from cp.tools.tool import Registry


@dataclass
class PipelineResponse:
    allowed: bool = False
    errored: bool = False
    message: str = ""
    result: Dict[str, Any] = field(default_factory=dict)


class Pipeline:
    """6 步统一管道(async)。控制面核心只调它,不认识任何具体工具。

    步骤:查找 → 提取权限 → 权限检查 → 资源扣减 → 执行(经 SandboxPort)→ 脱敏 → 审计(事件)。
    编排器不直接 execute(ch15 约束7);执行委托给 SandboxPort。
    """

    def __init__(self, registry: Registry, bus: Bus, sandbox):
        self.registry = registry
        self.bus = bus
        self.sandbox = sandbox

    async def call(self, sess: Session, sandbox_id: str, tool_name: str, params: Dict[str, Any]) -> PipelineResponse:
        # 步骤 1:查找工具。未知工具 = 拒绝。
        tool, ok = self.registry.get(tool_name)
        if not ok:
            await self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 2:提取权限资源(纯计算,不需 sandbox)。
        res = tool.permission_key(params)

        # 步骤 3:权限检查。
        if not sess.gate.allowed(tool_name, res):
            await self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 3.5:资源扣减。
        try:
            await sess.account.charge(Usage(steps=1))
        except QuotaExceeded:
            await self.bus.publish(Event(type="quota.exceeded", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="quota exceeded")

        # 步骤 4:执行——经 SandboxPort(不直接 tool.execute!)约束7
        action = {"tool": tool_name, "params": params}
        exec_result = await self.sandbox.exec_action(sandbox_id, action)
        if "error" in exec_result:
            await self.bus.publish(Event(type="tool.errored", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="tool error")
        result_data = exec_result["data"]

        # 步骤 5:脱敏。
        san_summary = []
        if sess.sanitizer is not None:
            sr = sess.sanitizer.sanitize(result_data)
            san_summary = [FieldSanitization(field=f.field, strategy=f.strategy) for f in sr.summary]
            result_data = sr.data

        # 步骤 6:审计事件(含脱敏摘要)。
        await self.bus.publish(Event(
            type="tool.called", session_id=sess.id, tool=tool_name,
            params=params, result=result_data, sanitize=san_summary,
        ))

        return PipelineResponse(allowed=True, result=result_data)
