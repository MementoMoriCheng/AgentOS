import json
from agentos_runtime.kernel_client import KernelClient


class FakeStub:
    def __init__(self):
        self.emit_calls = []

    def EmitRuntimeEvent(self, req, **kw):
        self.emit_calls.append(req)
        class R:
            pass
        return R()


def test_emit_event_sends_correct_proto():
    client = KernelClient("dummy.sock")
    fake = FakeStub()
    client._stub = fake
    client.emit_event(run_id="r1", session_id="s1", etype="runtime.step",
                      payload={"step_index": 0, "thought": "hi"})
    assert len(fake.emit_calls) == 1
    ev = fake.emit_calls[0]
    assert ev.type == "runtime.step"
    assert ev.run_id == "r1"
    assert ev.session_id == "s1"
    assert json.loads(ev.payload_json) == {"step_index": 0, "thought": "hi"}


def test_emit_event_empty_payload():
    client = KernelClient("dummy.sock")
    fake = FakeStub()
    client._stub = fake
    client.emit_event(run_id="r1", session_id="s1", etype="run.started", payload={})
    ev = fake.emit_calls[0]
    assert ev.type == "run.started"
    # 空 payload → payload_json 为空字符串
    assert ev.payload_json == ""
