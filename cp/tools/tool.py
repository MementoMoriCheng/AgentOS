import json
from dataclasses import dataclass
from typing import Any, Dict, Protocol

from cp.resource import Resource


@dataclass
class ToolResult:
    data: Dict[str, Any]


class Tool(Protocol):
    """自描述工具。控制面不认识任何具体工具,只调这个接口。
    加新工具 = 实现这个接口 + 注册,核心零改(开闭原则)。"""

    def name(self) -> str: ...

    def schema(self) -> str:
        """给 LLM 的 function schema(JSON 字符串)。"""
        ...

    def permission_key(self, params: Dict[str, Any]) -> Resource: ...

    async def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult: ...


class Registry:
    """工具注册表。"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        self._tools[t.name()] = t

    def get(self, name: str):
        t = self._tools.get(name)
        return (t, t is not None)
