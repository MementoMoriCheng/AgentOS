import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class FieldSanitization:
    """脱敏摘要的一条:字段名 + 策略,不含原始值。独立定义避免循环依赖。"""
    field: str
    strategy: str  # mask | hash | redact


@dataclass
class Event:
    """Kernel 内一切值得关注的事件。"""
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
    """事件总线接口(Week 2 会加 Kafka/Redis Stream 实现)。"""

    def publish(self, event: Event) -> None: ...
    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]: ...


class InProcess(Bus):
    """同步分发事件给所有订阅者。订阅者异常不影响主流程。"""

    def __init__(self):
        self._mu = threading.Lock()
        self._handlers: List[Optional[Callable]] = []

    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]:
        with self._mu:
            idx = len(self._handlers)
            self._handlers.append(handler)

        def _unsub():
            with self._mu:
                if idx < len(self._handlers):
                    self._handlers[idx] = None  # 置空;publish 跳过 None

        return _unsub

    def publish(self, event: Event) -> None:
        event.timestamp = time.time_ns()
        # 快照 handlers,避免回调里改订阅列表导致的竞态
        with self._mu:
            snapshot = list(self._handlers)
        for h in snapshot:
            if h is None:
                continue
            try:
                h(event)
            except Exception:
                pass  # 订阅者异常不影响主流程
