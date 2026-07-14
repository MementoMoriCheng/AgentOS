from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class PubPrimitive:
    """pub 原语:向事件流发布消息(异步广播)。经 MessageBusPort。"""
    name = "pub"

    def schema(self) -> Dict[str, Any]:
        return {"name": "pub", "description": "Publish event to a topic (async broadcast).",
                "parameters": {"type": "object",
                               "properties": {"topic": {"type": "string"},
                                              "payload": {"type": "object"}},
                               "required": ["topic", "payload"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="topic", id=params.get("topic", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        topic = params.get("topic", "")
        payload = params.get("payload", {})
        if ctx.bus is None:
            return PrimitiveResult(status="error", error="no message bus in context")
        await ctx.bus.publish(topic, payload)
        return PrimitiveResult(status="success", data={"topic": topic, "published": True})
