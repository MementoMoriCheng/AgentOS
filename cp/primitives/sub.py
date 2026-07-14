from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class SubPrimitive:
    """sub 原语:订阅 topic。handler_desc 是 agent 任务描述(执行时用)。
    Week 3:记录订阅;真实 handler 触发留 Week 4。"""
    name = "sub"

    def schema(self) -> Dict[str, Any]:
        return {"name": "sub", "description": "Subscribe to a topic.",
                "parameters": {"type": "object",
                               "properties": {"topic": {"type": "string"},
                                              "handler_desc": {"type": "string"}},
                               "required": ["topic", "handler_desc"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="topic", id=params.get("topic", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        topic = params.get("topic", "")
        handler_desc = params.get("handler_desc", "")
        if ctx.bus is None:
            return PrimitiveResult(status="error", error="no message bus in context")

        # 注册一个收集 handler(记录事件;真实 handler 触发由编排器在 Week 4 实现)
        async def _collector(msg):
            pass  # MVP:仅注册;事件到达时由 bus 消费循环分发

        ctx.bus.subscribe(topic, _collector)
        return PrimitiveResult(status="success", data={"topic": topic, "handler_desc": handler_desc, "subscribed": True})
