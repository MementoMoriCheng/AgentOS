from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class IoPrimitive:
    """io 原语:同步点对点请求(HTTP/gRPC)。Week 3 mock 实现。"""
    name = "io"

    def schema(self) -> Dict[str, Any]:
        return {"name": "io", "description": "Sync request-response (http/mcp).",
                "parameters": {"type": "object",
                               "properties": {"protocol": {"type": "string"},
                                              "endpoint": {"type": "string"},
                                              "method": {"type": "string"},
                                              "body": {"type": "string"}},
                               "required": ["protocol", "endpoint"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="http_url", id=params.get("endpoint", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        # MOCK:返回固定 HTTP 响应。真实实现用 httpx/aiohttp。
        endpoint = params.get("endpoint", "")
        protocol = params.get("protocol", "http")
        return PrimitiveResult(status="success", data={
            "status": 200,
            "body": f"[mock io] {protocol} {endpoint}",
            "headers": {"content-type": "text/plain"},
        })
