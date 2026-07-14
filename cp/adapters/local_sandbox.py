import uuid
from typing import Any, Dict

from cp.tools.tool import Registry


class LocalSandboxExecutor:
    """SandboxPort 的本地实现。进程内执行(调 tool.execute),接口按远程设计。
    Week 3 加 RemoteSandboxExecutor 走消息总线时,调用方零改(ch15 约束5/7)。"""

    def __init__(self, registry: Registry):
        self._reg = registry
        self._sandboxes: Dict[str, Dict[str, Any]] = {}

    async def create(self, config: Dict[str, Any]) -> str:
        sid = f"sbx-{uuid.uuid4().hex[:12]}"
        self._sandboxes[sid] = config
        return sid

    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action.get("tool", "")
        params = action.get("params", {})
        tool, ok = self._reg.get(tool_name)
        if not ok:
            return {"error": f"unknown tool: {tool_name}"}
        try:
            result = await tool.execute(None, params)
            return {"data": result.data}
        except Exception as e:
            return {"error": str(e)}

    async def destroy(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)
