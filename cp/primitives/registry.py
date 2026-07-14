from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from cp.resource import Resource


@dataclass
class PrimitiveResult:
    status: str = "success"  # "success" | "error" | "timeout"
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


class PrimitiveContext:
    """原语执行上下文:持有 session/sandbox_id/sandbox/bus/state 等依赖。"""
    def __init__(self, session=None, sandbox_id="", sandbox=None, bus=None, state=None):
        self.session = session
        self.sandbox_id = sandbox_id
        self.sandbox = sandbox
        self.bus = bus
        self.state = state


class Primitive(Protocol):
    """原语:控制面唯一认识的执行货币。每个原语经安全管道执行。"""
    name: str
    def schema(self) -> Dict[str, Any]: ...
    def permission_key(self, params: Dict[str, Any]) -> Resource: ...
    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult: ...


class PrimitiveRegistry:
    def __init__(self):
        self._prims: Dict[str, Primitive] = {}

    def register(self, p: Primitive) -> None:
        self._prims[p.name] = p

    def get(self, name: str):
        p = self._prims.get(name)
        return (p, p is not None)

    def names(self) -> List[str]:
        return list(self._prims.keys())
