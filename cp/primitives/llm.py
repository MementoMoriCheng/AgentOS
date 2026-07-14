from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class LlmPrimitive:
    """llm 原语:调用 LLM API。有 client 时真实调用;无 client 时 mock。"""
    name = "llm"

    def __init__(self, client=None):
        self._client = client

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
        if self._client is not None:
            return await self._call_real(params)
        return await self._call_mock(params)

    async def _call_real(self, params: Dict[str, Any]) -> PrimitiveResult:
        messages = params.get("messages", [])
        result = await self._client.chat(messages)
        return PrimitiveResult(status="success", data={
            "content": result.get("content", ""),
            "tool_calls": result.get("tool_calls", []),
        })

    async def _call_mock(self, params: Dict[str, Any]) -> PrimitiveResult:
        messages = params.get("messages", [])
        last_msg = messages[-1] if messages else {}
        user_text = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
        return PrimitiveResult(status="success", data={
            "content": f"[mock llm] echo: {user_text[:50]}",
            "model": params.get("model", "mock"),
            "tokens_in": len(str(user_text)),
            "tokens_out": 10,
        })
