import json

from cp.eventbus.bus import Event


def event_to_agent_json(e: Event) -> dict:
    """把 cp/Event 转成前端 AgentEvent JSON 形状。
    params/result/payload 序列化成 JSON 字符串(前端约定,见 web-src/src/lib/api.ts)。"""
    return {
        "type": e.type,
        "session_id": e.session_id,
        "run_id": e.run_id,
        "tool": e.tool,
        "params_json": json.dumps(e.params, default=str),
        "result_json": json.dumps(e.result, default=str),
        "payload_json": json.dumps(e.payload, default=str),
        "identity": e.identity,
        "timestamp": e.timestamp,
        "sanitize": [{"field": f.field, "strategy": f.strategy} for f in e.sanitize],
    }
