from cp.eventbus.bus import Event, FieldSanitization
from cp.server.serialize import event_to_agent_json


def test_basic_event_serialization():
    e = Event(type="primitive.called", session_id="s1", run_id="r1", tool="read")
    out = event_to_agent_json(e)
    assert out["type"] == "primitive.called"
    assert out["run_id"] == "r1"
    assert out["session_id"] == "s1"
    assert out["params_json"] == "{}"
    assert out["result_json"] == "{}"
    assert out["sanitize"] == []


def test_event_with_params_result():
    e = Event(type="tool.called", session_id="s1", run_id="r1", tool="read",
              params={"path": "x"}, result={"content": "y"})
    out = event_to_agent_json(e)
    assert '"path"' in out["params_json"]
    assert '"content"' in out["result_json"]


def test_sanitize_list_serialized():
    e = Event(type="tool.called", sanitize=[FieldSanitization("phone", "mask")])
    out = event_to_agent_json(e)
    assert out["sanitize"] == [{"field": "phone", "strategy": "mask"}]


def test_payload_json_is_string():
    e = Event(type="run.started", run_id="r1", payload={"task": "hi", "max_steps": 5})
    out = event_to_agent_json(e)
    assert isinstance(out["payload_json"], str)
    assert '"task"' in out["payload_json"]
