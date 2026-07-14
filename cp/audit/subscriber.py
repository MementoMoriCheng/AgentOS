import json

from cp.audit.ledger import Entry, Ledger
from cp.eventbus.bus import Bus, Event


def register_audit_subscriber(ledger: Ledger, bus: Bus) -> None:
    """让 ledger 订阅 bus 上的相关事件并写审计。审计逻辑的唯一集中点。"""

    async def _on_event(e: Event) -> None:
        outcome = _outcome_for(e.type)
        if outcome == "":
            return  # 不审计的事件类型
        await ledger.append(Entry(
            session_id=e.session_id,
            tool=e.tool,
            params_json=json.dumps(e.params, default=str),
            outcome=outcome,
            result_json=json.dumps(e.result, default=str),
        ))

    bus.subscribe(_on_event)


def _outcome_for(event_type: str) -> str:
    return {
        "tool.called": "allowed",
        "tool.denied": "denied",
        "tool.errored": "error",
        "session.started": "session_started",
        "session.ended": "session_ended",
        "quota.exceeded": "quota_exceeded",
    }.get(event_type, "")
