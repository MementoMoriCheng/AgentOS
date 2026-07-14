"""V2 ch11 故障恢复:快照 + 重水合。每步执行后存 checkpoint 到 Redis;
沙箱死亡时读最新 checkpoint 重建 session 续跑。"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class SessionSnapshot:
    """可序列化的 session 状态快照。不可序列化的成员(Gate/Sanitizer)从 YAML 重新加载。"""
    session_id: str
    policy_path: str = ""
    sanitization_path: str = ""
    identity: str = "local"
    used_steps: int = 0
    used_tokens: int = 0
    messages: List[Dict[str, Any]] = field(default_factory=list)
    step: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SessionSnapshot":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


class Checkpoint:
    """checkpoint 存取。存 Redis:checkpoint:{session_id}:{step} → snapshot JSON。
    另存 checkpoint:{session_id}:latest → 最新 step 号(快速检索)。"""

    def __init__(self, state_port):
        """state_port: StatePort 实现(RedisStatePort)。"""
        self._state = state_port

    async def save(self, snapshot: SessionSnapshot) -> None:
        """保存快照(每步后调用)。更新 latest 指针。"""
        key = f"checkpoint:{snapshot.session_id}:{snapshot.step}"
        await self._state.save_session(key, snapshot.to_dict())
        await self._state.save_session(f"checkpoint:{snapshot.session_id}:latest",
                                       {"step": snapshot.step})

    async def load_latest(self, session_id: str) -> Optional[SessionSnapshot]:
        """读最新 checkpoint。无则返回 None。"""
        latest = await self._state.get_session(f"checkpoint:{session_id}:latest")
        if latest is None:
            return None
        step = latest.get("step", 0)
        snap = await self._state.get_session(f"checkpoint:{session_id}:{step}")
        if snap is None:
            return None
        return SessionSnapshot.from_dict(snap)

    async def load_at(self, session_id: str, step: int) -> Optional[SessionSnapshot]:
        """读指定 step 的 checkpoint。"""
        snap = await self._state.get_session(f"checkpoint:{session_id}:{step}")
        return SessionSnapshot.from_dict(snap) if snap else None


async def rehydrate(snapshot: SessionSnapshot, policy_loader, sanitizer_loader) -> Dict[str, Any]:
    """重水合:从快照重建 session 可用状态。
    policy_loader/sanitizer_loader 是异步函数:path → Policy/Sanitizer(从 YAML 重新加载)。
    返回重建后的状态 dict(account 用量恢复;Gate/Sanitizer 重新构造)。"""
    from cp.policy.gate import Gate
    from cp.session.account import Account, ResourceQuota, Usage
    policy = await policy_loader(snapshot.policy_path)
    sanitizer = await sanitizer_loader(snapshot.sanitization_path)
    account = Account(ResourceQuota(max_steps=policy.max_steps, max_tokens=policy.max_tokens))
    # 恢复用量(已消耗的 steps/tokens)
    account._used = Usage(steps=snapshot.used_steps, tokens=snapshot.used_tokens)
    return {
        "session_id": snapshot.session_id,
        "identity": snapshot.identity,
        "policy": policy,
        "gate": Gate(policy),
        "sanitizer": sanitizer,
        "account": account,
        "messages": snapshot.messages,
        "step": snapshot.step,
    }
