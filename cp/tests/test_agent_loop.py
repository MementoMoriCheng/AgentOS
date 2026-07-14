import json
import tempfile
from cp.agent_loop import run_agent_loop
from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.llm.mock import MockLLMClient
from cp.policy.policy import Policy, Rule
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session


class MockSandbox:
    async def create(self, config):
        return "sbx"

    async def exec_action(self, sid, action):
        if action.get("tool") == "fs_read":
            return {"data": {"content": "42"}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


async def test_loop_no_tool_calls():
    llm = MockLLMClient([{"role": "assistant", "content": "The answer is 42."}])
    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local",
                           Policy(permissions=[], max_steps=10, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        result = await run_agent_loop("what is the answer", llm, None, sess, None, [])
        assert result["termination"] == "completed"
        assert result["final_answer"] == "The answer is 42."
        assert result["steps_used"] == 1


async def test_loop_with_tool_call_then_answer():
    llm = MockLLMClient([
        {"role": "assistant", "content": "Let me read the file.",
         "tool_calls": [{"id": "tc1", "type": "function",
                         "function": {"name": "read",
                                      "arguments": json.dumps({"source": "file:///data/x"})}}]},
        {"role": "assistant", "content": "The file contains 42."},
    ])
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        executor = PrimitiveExecutor(reg, bus)
        pol = Policy(permissions=[Rule("path", "/data/**", ["read"])], max_steps=10, max_tokens=1000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=None)
        result = await run_agent_loop("read the file", llm, executor, sess, ctx, [])
        assert result["termination"] == "completed"
        assert "42" in result["final_answer"]
        assert result["steps_used"] == 2


async def test_loop_step_limit():
    llm = MockLLMClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"tc{i}", "type": "function",
             "function": {"name": "read", "arguments": "{}"}}]}
        for i in range(30)
    ])
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        executor = PrimitiveExecutor(reg, bus)
        pol = Policy(permissions=[Rule("path", "/**", ["read"])], max_steps=50, max_tokens=100000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=None)
        result = await run_agent_loop("loop forever", llm, executor, sess, ctx, [], max_steps=3)
        assert result["termination"] == "step_limit"


async def test_loop_denied_tool_records_error():
    """工具被 gate 拒绝时,错误消息进 messages,loop 继续。"""
    llm = MockLLMClient([
        {"role": "assistant", "content": "try denied",
         "tool_calls": [{"id": "tc1", "type": "function",
                         "function": {"name": "read", "arguments": json.dumps({"source": "file:///etc/shadow"})}}]},
        {"role": "assistant", "content": "ok gave up"},
    ])
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        executor = PrimitiveExecutor(reg, bus)
        # policy 不允许 /etc/shadow
        pol = Policy(permissions=[Rule("path", "/data/**", ["read"])], max_steps=10, max_tokens=1000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=None)
        result = await run_agent_loop("try", llm, executor, sess, ctx, [])
        assert result["termination"] == "completed"
        # 第二轮 llm 收到了 denied 消息(在 calls[1] 里应有 tool role message)
        tool_msgs = [m for m in llm.calls[1] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "denied" in tool_msgs[0]["content"]
