from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class StatePort(Protocol):
    """状态外化接口。所有持久/热状态经此存取,不进进程内存(ch15 约束3/6)。"""

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    async def save_session(self, session_id: str, state: Dict[str, Any]) -> None: ...
    async def delete_session(self, session_id: str) -> None: ...


@runtime_checkable
class MessageBusPort(Protocol):
    """消息总线接口。控制面↔沙箱唯一通信通道;事件流经此(ch15 约束4)。"""

    async def publish(self, topic: str, message: Dict[str, Any]) -> None: ...
    def subscribe(self, topic: str, handler: Callable) -> Callable[[], None]: ...


@runtime_checkable
class SandboxPort(Protocol):
    """沙箱执行接口。按远程设计(ch15 约束5);编排器不直接 execute(ch15 约束7)。"""

    async def create(self, config: Dict[str, Any]) -> str: ...
    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]: ...
    async def destroy(self, sandbox_id: str) -> None: ...


@runtime_checkable
class AuthPort(Protocol):
    """认证/权限接口。"""

    async def check_permission(self, tenant_id: str, agent_id: str, action: str) -> bool: ...


@runtime_checkable
class AuditPort(Protocol):
    """审计接口。经消息总线旁路订阅,不散落(ch15 约束4)。"""

    async def record(self, event: Dict[str, Any]) -> None: ...
