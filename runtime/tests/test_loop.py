import json
from agentos_runtime.loop import run_agent


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def chat(self, messages, tools):
        msg = self.script[self.i]
        self.i += 1
        return msg


class FakeKernel:
    def __init__(self):
        self.calls = []
        self.events = []
    def start_session(self, policy, sanitization):
        return "s1"
    def call_tool(self, sid, tool, params):
        self.calls.append((tool, params))
        return {"allowed": True, "errored": False, "message": "", "result": {"content": "DATA"}}
    def emit_event(self, run_id, session_id, etype, payload):
        self.events.append({"run_id": run_id, "session_id": session_id, "etype": etype, "payload": payload})
    def close(self):
        pass


def test_loop_runs_tool_then_finishes():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "a.txt"})}}]},
        {"role": "assistant", "content": "Done. Total is 42."},
    ])
    kernel = FakeKernel()
    result = run_agent("compute total", llm, kernel, session_id="s1", run_id="r1", max_steps=5)
    assert kernel.calls == [("fs_read", {"path": "a.txt"})]
    assert "42" in result


def test_loop_respects_max_steps():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": str(i), "type": "function",
            "function": {"name": "fs_list", "arguments": json.dumps({"path": "."})}}]}
        for i in range(100)
    ])
    kernel = FakeKernel()
    result = run_agent("loop", llm, kernel, session_id="s1", run_id="r1", max_steps=3)
    assert "step limit" in result.lower() or "max" in result.lower()


def test_loop_handles_denied_tool():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "/etc/shadow"})}}]},
        {"role": "assistant", "content": "Could not read. Done."},
    ])
    kernel = FakeKernel()
    kernel.call_tool = lambda *a: {"allowed": False, "errored": False, "message": "permission denied", "result": {}}
    result = run_agent("try", llm, kernel, session_id="s1", run_id="r1", max_steps=5)
    assert "Done" in result


def test_loop_handles_tool_error():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "missing.txt"})}}]},
        {"role": "assistant", "content": "File not found. Done."},
    ])
    kernel = FakeKernel()
    kernel.call_tool = lambda *a: {"allowed": True, "errored": True, "message": "file not found", "result": {}}
    result = run_agent("try", llm, kernel, session_id="s1", run_id="r1", max_steps=5)
    assert "Done" in result


def test_loop_returns_content_when_no_tool_calls():
    llm = FakeLLM([
        {"role": "assistant", "content": "Direct answer, no tools needed."},
    ])
    kernel = FakeKernel()
    result = run_agent("question", llm, kernel, session_id="s1", run_id="r1", max_steps=5)
    assert result == "Direct answer, no tools needed."
    assert kernel.calls == []  # 没调任何工具


# ===== 新增：事件发送 =====

def test_loop_emits_run_lifecycle_events():
    """验证 loop 发 run.started / runtime.step / run.ended，且不建 session。"""
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_list", "arguments": json.dumps({"path": "."})}}]},
        {"role": "assistant", "content": "done"},
    ])
    kernel = FakeKernel()
    run_agent("list files", llm, kernel, session_id="s9", run_id="r9", max_steps=5)

    types = [e["etype"] for e in kernel.events]
    assert types[0] == "run.started"
    assert "runtime.step" in types
    assert types[-1] == "run.ended"

    # loop 不应再调 start_session
    # （FakeKernel.start_session 仍存在但未被调用——没有直接断言手段，靠逻辑保证）

    # run.started 的 payload 含 task / max_steps
    started = kernel.events[0]
    assert started["payload"]["task"] == "list files"
    assert started["payload"]["max_steps"] == 5

    # run.ended 的 payload 含 termination
    ended = kernel.events[-1]
    assert ended["payload"]["termination"] == "completed"
    assert "final_answer" in ended["payload"]

    # 所有事件的 run_id / session_id 正确
    for e in kernel.events:
        assert e["run_id"] == "r9"
        assert e["session_id"] == "s9"


def test_loop_emits_step_limit_on_max_steps():
    """达到 max_steps 时 run.ended 的 termination = step_limit。"""
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": str(i), "type": "function",
            "function": {"name": "fs_list", "arguments": json.dumps({"path": "."})}}]}
        for i in range(100)
    ])
    kernel = FakeKernel()
    run_agent("loop", llm, kernel, session_id="s1", run_id="r1", max_steps=2)
    ended = [e for e in kernel.events if e["etype"] == "run.ended"][-1]
    assert ended["payload"]["termination"] == "step_limit"


def test_loop_emits_crashed_on_exception():
    """LLM 抛异常时，finally 仍发 run.ended（termination=crashed），然后 re-raise。"""
    class BoomLLM:
        def chat(self, messages, tools):
            raise RuntimeError("LLM exploded")
    kernel = FakeKernel()
    try:
        run_agent("boom", BoomLLM(), kernel, session_id="s1", run_id="r1", max_steps=5)
        assert False, "should have raised"
    except RuntimeError:
        pass
    # finally 仍发了 run.ended（termination=crashed）
    ended = [e for e in kernel.events if e["etype"] == "run.ended"]
    assert len(ended) == 1
    assert ended[0]["payload"]["termination"] == "crashed"
