import httpx
from typing import Any, Dict

from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class IoPrimitive:
    """io 原语:同步点对点 HTTP 请求(GET/POST/PUT/DELETE)。
    permission_key 用 http_url 类型,Gate 默认拒——policy 需显式放行域名。
    真实实现用 httpx;无网络时测试可用 mock_server。"""
    name = "io"

    def schema(self) -> Dict[str, Any]:
        return {"name": "io", "description": "Sync HTTP request (GET/POST/PUT/DELETE).",
                "parameters": {"type": "object",
                               "properties": {"method": {"type": "string"},
                                              "url": {"type": "string"},
                                              "headers": {"type": "object"},
                                              "body": {"type": "string"},
                                              "timeout": {"type": "number"}},
                               "required": ["method", "url"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        # 权限检查用完整 url;Gate 对 http_url 走精确匹配
        return Resource(type="http_url", id=params.get("url", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        method = params.get("method", "GET").upper()
        url = params.get("url", "")
        headers = params.get("headers", {}) or {}
        body = params.get("body")
        timeout = params.get("timeout", 30.0)
        if not url:
            return PrimitiveResult(status="error", error="missing url")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                req_kwargs = {"headers": headers}
                if body is not None and method in ("POST", "PUT", "PATCH"):
                    req_kwargs["content"] = body
                resp = await client.request(method, url, **req_kwargs)
            return PrimitiveResult(status="success", data={
                "status": resp.status_code,
                "body": resp.text,
                "headers": dict(resp.headers),
            })
        except httpx.TimeoutException:
            return PrimitiveResult(status="error", error=f"timeout after {timeout}s")
        except httpx.HTTPError as e:
            return PrimitiveResult(status="error", error=f"http error: {e}")
        except Exception as e:  # noqa: BLE001
            return PrimitiveResult(status="error", error=f"io error: {e}")
