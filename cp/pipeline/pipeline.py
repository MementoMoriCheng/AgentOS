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
    """6 步统一管道。控制面核心只调它,不认识任何具体工具。

    步骤:查找 → 提取权限 → 权限检查 → 资源扣减 → 执行 → 脱敏 → 审计(事件)。
    """

    def __init__(self, registry: Registry, bus: Bus):
        self.registry = registry
        self.bus = bus

    def call(self, sess: Session, tool_name: str, params: Dict[str, Any]) -> PipelineResponse:
        # 步骤 1:查找工具。未知工具 = 拒绝(不泄露工具清单细节)。
        tool, ok = self.registry.get(tool_name)
        if not ok:
            self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 2:提取权限资源(工具自描述)。
        res = tool.permission_key(params)

        # 步骤 3:权限检查。不通过 → 拒绝 + 审计(拒绝原因不回传,防泄露)。
        if not sess.gate.allowed(tool_name, res):
            self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 3.5:资源扣减。超限 → 硬终止 + quota.exceeded 事件。
        try:
            sess.account.charge(Usage(steps=1))
        except QuotaExceeded:
            self.bus.publish(Event(type="quota.exceeded", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="quota exceeded")

        # 步骤 4:执行工具。
        try:
            result = tool.execute(None, params)
        except Exception:
            self.bus.publish(Event(type="tool.errored", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="tool error")

        # 步骤 5:脱敏(第一道安全防线,独立于工具)。保留摘要进事件。
        san_summary = []
        if sess.sanitizer is not None:
            sr = sess.sanitizer.sanitize(result.data)
            result.data = sr.data
            san_summary = [FieldSanitization(field=f.field, strategy=f.strategy) for f in sr.summary]

        # 步骤 6:审计(通过事件触发 AuditSubscriber,不散落)。含脱敏摘要。
        self.bus.publish(Event(
            type="tool.called", session_id=sess.id, tool=tool_name,
            params=params, result=result.data, sanitize=san_summary,
        ))

        return PipelineResponse(allowed=True, result=result.data)
