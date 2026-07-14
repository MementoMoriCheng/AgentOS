from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class LlmPrimitive:
    """llm 原语:调用 LLM API。Week 3 mock 实现(返回固定响应);
    Week 4 接真实 provider(DeepSeek/LiteLLM)。"""
    name = "llm"

    def schema(self) -> Dict[str, Any]:
        return {"name": "llm", "description": "Call LLM for inference.",
                "parameters": {"type": "object",
                               "properties": {"model": {"type": "string"},
                                              "messages": {"type": "array"},
                                              "temperature": {"type": "number"}},
                               "required": ["model", "messages"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="llm", id=params.get("model", "default"))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        # MOCK:返回固定响应。真实实现接 LLM provider。
        messages = params.get("messages", [])
        last_msg = messages[-1] if messages else {}
        user_text = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
        return PrimitiveResult(status="success", data={
            "content": f"[mock llm] echo: {user_text[:50]}",
            "model": params.get("model", "mock"),
            "tokens_in": len(str(user_text)),
            "tokens_out": 10,
        })
