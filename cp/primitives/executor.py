from dataclasses import dataclass, field
from typing import Any, Dict

from cp.eventbus.bus import Bus, Event, FieldSanitization
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry, PrimitiveResult
from cp.session.account import QuotaExceeded, Usage
from cp.session.session import Session


@dataclass
class PrimitiveResponse:
    allowed: bool = False
    errored: bool = False
    message: str = ""
    result: Dict[str, Any] = field(default_factory=dict)


class PrimitiveExecutor:
    """原语经安全管道执行。镜像 Pipeline 的 6 步,但步骤4 调 primitive.execute
    (原语内部各自路由:sandbox/URL/bus/mock)。约束7 不违反:编排器不直接
    执行命令,原语是抽象层,exec 原语内部再委托 sandbox。"""

    def __init__(self, registry: PrimitiveRegistry, bus: Bus):
        self.registry = registry
        self.bus = bus

    async def call(self, sess: Session, ctx: PrimitiveContext, prim_name: str,
                   params: Dict[str, Any]) -> PrimitiveResponse:
        # 步骤1:查找原语
        prim, ok = self.registry.get(prim_name)
        if not ok:
            await self.bus.publish(Event(type="primitive.denied", session_id=sess.id, tool=prim_name, params=params))
            return PrimitiveResponse(allowed=False, message="unknown primitive")

        # 步骤2:permission_key(纯计算)
        res = prim.permission_key(params)

        # 步骤3:权限检查
        if not sess.gate.allowed(prim_name, res):
            await self.bus.publish(Event(type="primitive.denied", session_id=sess.id, tool=prim_name, params=params))
            return PrimitiveResponse(allowed=False, message="permission denied")

        # 步骤3.5:配额
        try:
            await sess.account.charge(Usage(steps=1))
        except QuotaExceeded:
            await self.bus.publish(Event(type="quota.exceeded", session_id=sess.id, tool=prim_name, params=params))
            return PrimitiveResponse(errored=True, message="quota exceeded")

        # 步骤4:执行原语(原语内部路由)
        try:
            presult: PrimitiveResult = await prim.execute(ctx, params)
        except Exception as e:
            await self.bus.publish(Event(type="primitive.errored", session_id=sess.id, tool=prim_name, params=params))
            return PrimitiveResponse(errored=True, message=f"primitive error: {e}")

        if presult.status != "success":
            await self.bus.publish(Event(type="primitive.errored", session_id=sess.id, tool=prim_name, params=params))
            return PrimitiveResponse(errored=True, message=presult.error or "primitive failed")

        result_data = presult.data

        # 步骤5:脱敏
        san_summary = []
        if sess.sanitizer is not None:
            sr = sess.sanitizer.sanitize(result_data)
            san_summary = [FieldSanitization(field=f.field, strategy=f.strategy) for f in sr.summary]
            result_data = sr.data

        # 步骤6:审计
        await self.bus.publish(Event(
            type="primitive.called", session_id=sess.id, tool=prim_name,
            params=params, result=result_data, sanitize=san_summary,
        ))

        return PrimitiveResponse(allowed=True, result=result_data)
