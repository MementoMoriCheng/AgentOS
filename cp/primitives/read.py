import urllib.parse
from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class ReadPrimitive:
    """read 原语:按 URL scheme 路由。file://→沙箱文件系统;kv://→Redis StatePort。"""
    name = "read"

    def schema(self) -> Dict[str, Any]:
        return {"name": "read", "description": "Read from a location via URL scheme.",
                "parameters": {"type": "object",
                               "properties": {"source": {"type": "string"}},
                               "required": ["source"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        source = params.get("source", "")
        parsed = urllib.parse.urlparse(source)
        scheme = parsed.scheme or "file"
        if scheme == "file":
            return Resource(type="path", id=parsed.path)
        return Resource(type=scheme, id=parsed.netloc + parsed.path)

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        source = params.get("source", "")
        parsed = urllib.parse.urlparse(source)
        scheme = parsed.scheme or "file"
        if scheme == "file":
            result = await ctx.sandbox.exec_action(ctx.sandbox_id,
                                                   {"tool": "fs_read", "params": {"path": parsed.path}})
            if "error" in result:
                return PrimitiveResult(status="error", error=result["error"])
            return PrimitiveResult(status="success", data=result.get("data", {}))
        elif scheme == "kv":
            key = (parsed.netloc + parsed.path).strip("/")
            value = await ctx.state.get_session(key) if ctx.state else None
            return PrimitiveResult(status="success", data={"value": value})
        return PrimitiveResult(status="error", error=f"unsupported scheme: {scheme}")
