from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class ExecPrimitive:
    """exec 原语:在沙箱内执行命令。经 SandboxPort。"""
    name = "exec"

    def schema(self) -> Dict[str, Any]:
        return {"name": "exec", "description": "Execute shell command in sandbox.",
                "parameters": {"type": "object",
                               "properties": {"command": {"type": "string"},
                                              "workdir": {"type": "string"}},
                               "required": ["command"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="shell", id=params.get("command", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        command = params.get("command", "")
        workdir = params.get("workdir", "/workspace")
        result = await ctx.sandbox.exec_action(ctx.sandbox_id,
                                               {"tool": "shell", "params": {"command": command, "workdir": workdir}})
        if "error" in result:
            return PrimitiveResult(status="error", error=result["error"])
        return PrimitiveResult(status="success", data=result.get("data", {}))
