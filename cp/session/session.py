from dataclasses import dataclass

from cp.audit.ledger import Ledger
from cp.policy.gate import Gate
from cp.policy.policy import Policy
from cp.sanitize.sanitizer import Sanitizer
from cp.session.account import Account, ResourceQuota


@dataclass
class Session:
    """一个运行中 agent 的内核侧状态。Pipeline 不放这里(避免循环依赖)。"""
    id: str
    identity: str
    policy: Policy
    gate: Gate
    sanitizer: Sanitizer
    account: Account
    ledger: Ledger
    tenant_id: str = ""  # 租户隔离标识；空=不隔离（开发默认）

    @classmethod
    def new(cls, sid: str, identity: str, pol: Policy, san: Sanitizer, ledger: Ledger,
            tenant_id: str = "") -> "Session":
        return cls(
            id=sid,
            identity=identity,
            policy=pol,
            gate=Gate(pol),
            sanitizer=san,
            account=Account(ResourceQuota(max_steps=pol.max_steps, max_tokens=pol.max_tokens)),
            ledger=ledger,
            tenant_id=tenant_id,
        )
