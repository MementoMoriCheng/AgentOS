import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class FieldSanitization:
    field: str
    strategy: str


@dataclass
class Event:
    type: str = ""
    session_id: str = ""
    run_id: str = ""
    tool: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    identity: str = ""
    sanitize: List[FieldSanitization] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0


class Bus:
    """事件总线接口(async)。Week 3 可换 RedisStreamMessageBus。"""

    async def publish(self, event: Event) -> None: ...
    def subscribe(self, handler: Callable) -> Callable[[], None]: ...


class InProcess(Bus):
    """async 分发事件给所有订阅者。订阅者异常不影响主流程。"""

    def __init__(self):
        self._handlers: List[Optional[Callable]] = []

    def subscribe(self, handler: Callable) -> Callable[[], None]:
        idx = len(self._handlers)
        self._handlers.append(handler)

        def _unsub():
            if idx < len(self._handlers):
                self._handlers[idx] = None
        return _unsub

    async def publish(self, event: Event) -> None:
        event.timestamp = time.time_ns()
        snapshot = list(self._handlers)
        for h in snapshot:
            if h is None:
                continue
            try:
                await h(event)
            except Exception:
                pass
