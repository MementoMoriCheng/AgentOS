from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class SubPrimitive:
    """sub 原语:订阅 topic。handler 收到消息时写入 ctx.inbox[topic]。
    agent loop 每步后检查 inbox,把新消息注入观察。"""
    name = "sub"

    def schema(self) -> Dict[str, Any]:
        return {"name": "sub", "description": "Subscribe to a topic; messages arrive in agent inbox.",
                "parameters": {"type": "object",
                               "properties": {"topic": {"type": "string"},
                                              "handler_desc": {"type": "string"}},
                               "required": ["topic"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="topic", id=params.get("topic", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        topic = params.get("topic", "")
        handler_desc = params.get("handler_desc", "")
        if ctx.bus is None:
            return PrimitiveResult(status="error", error="no message bus in context")
        ctx.inbox.setdefault(topic, [])

        # handler:消息进收件箱,agent loop 下一步可见
        async def _collector(msg):
            ctx.inbox[topic].append(msg)

        ctx.bus.subscribe(topic, _collector)
        return PrimitiveResult(status="success", data={"topic": topic, "handler_desc": handler_desc, "subscribed": True})
