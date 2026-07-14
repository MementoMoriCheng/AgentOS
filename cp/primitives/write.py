import urllib.parse
from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class WritePrimitive:
    """write 原语:按 URL scheme 路由。file://→沙箱文件系统;kv://→Redis StatePort。"""
    name = "write"

    def schema(self) -> Dict[str, Any]:
        return {"name": "write", "description": "Write to a location via URL scheme.",
                "parameters": {"type": "object",
                               "properties": {"target": {"type": "string"},
                                              "data": {"type": "string"},
                                              "mode": {"type": "string"}},
                               "required": ["target", "data"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        target = params.get("target", "")
        parsed = urllib.parse.urlparse(target)
        scheme = parsed.scheme or "file"
        if scheme == "file":
            return Resource(type="path", id=parsed.path)
        return Resource(type=scheme, id=parsed.netloc + parsed.path)

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        target = params.get("target", "")
        data = params.get("data", "")
        mode = params.get("mode", "overwrite")
        parsed = urllib.parse.urlparse(target)
        scheme = parsed.scheme or "file"
        if scheme == "file":
            result = await ctx.sandbox.exec_action(ctx.sandbox_id,
                                                   {"tool": "fs_write", "params": {"path": parsed.path, "content": data}})
            if "error" in result:
                return PrimitiveResult(status="error", error=result["error"])
            return PrimitiveResult(status="success", data=result.get("data", {}))
        elif scheme == "kv":
            key = (parsed.netloc + parsed.path).strip("/")
            if ctx.state:
                await ctx.state.save_session(key, {"value": data})
            return PrimitiveResult(status="success", data={"key": key, "written": True})
        return PrimitiveResult(status="error", error=f"unsupported scheme: {scheme}")
