"""AuditPort adapter:把事件 dict 记录到 hash 链 Ledger。
implements cp.ports.AuditPort.record(event)。"""
import json
from typing import Any, Dict

from cp.audit.ledger import Entry, Ledger


class LedgerAuditPort:
    """bus 事件 -> Ledger.append(Entry)。hash 链不可篡改。"""

    def __init__(self, ledger: Ledger):
        self._ledger = ledger

    async def record(self, event: Dict[str, Any]) -> None:
        """把 event dict 转成 Entry 记入 hash 链。

        outcome 优先取 event['outcome'];否则从 type 去掉前缀(primitive./tool.)得到。
        """
        etype = event.get("type", "")
        outcome = event.get("outcome") or etype.replace("primitive.", "").replace("tool.", "")
        e = Entry(
            session_id=event.get("session_id", ""),
            tool=event.get("tool", ""),
            params_json=event.get("params_json") or json.dumps(event.get("params", {})),
            outcome=outcome,
            result_json=json.dumps(event.get("result", {})),
        )
        await self._ledger.append(e)
