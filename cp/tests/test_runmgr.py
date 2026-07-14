import asyncio
import json
import os
import tempfile

from cp.llm.mock import MockLLMClient
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveRegistry
from cp.server.runmgr import RunManager


class MockSandbox:
    async def create(self, config):
        return "sbx-mock"

    async def exec_action(self, sid, action):
        if action.get("tool") == "fs_read":
            return {"data": {"content": "42"}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


def _executor_factory(bus):
    reg = PrimitiveRegistry()
    reg.register(ReadPrimitive())
    return PrimitiveExecutor(reg, bus)


def _write_open_policy(d):
    """允许 read 所有 path 的临时 policy。"""
    pol_path = os.path.join(d, "p.yaml")
    with open(pol_path, "w") as f:
        f.write("permissions:\n  - resource_type: path\n    pattern: '**'\n    actions: [read]\nmax_steps: 10\n")
    return pol_path


async def test_submit_creates_run_and_completes(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, MockSandbox(), state,
                     executor_factory=_executor_factory,
                     llm=MockLLMClient([
                         {"role": "assistant", "content": "let me read",
                          "tool_calls": [{"id": "tc1", "type": "function",
                                          "function": {"name": "read",
                                                       "arguments": json.dumps({"source": "file:data/x.txt"})}}]},
                         {"role": "assistant", "content": "The answer is 42."},
                     ]))
    with tempfile.TemporaryDirectory() as d:
        pol_path = _write_open_policy(d)
        run = await mgr.submit("read and answer", pol_path, "", max_steps=5)
        assert run.run_id.startswith("run-")
        for _ in range(100):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        assert run.status == "ended"
        assert "42" in run.final_answer
        types = [e.type for e in run.events]
        assert "run.started" in types
        assert "primitive.called" in types
        assert "run.ended" in types


async def test_events_carry_run_id(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, MockSandbox(), state,
                     executor_factory=_executor_factory,
                     llm=MockLLMClient([{"role": "assistant", "content": "done right away"}]))
    with tempfile.TemporaryDirectory() as d:
        pol_path = _write_open_policy(d)
        run = await mgr.submit("task", pol_path, "", max_steps=3)
        for _ in range(100):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        assert run.events, "should have events"
        for e in run.events:
            assert e.run_id == run.run_id, f"event {e.type} missing run_id"


async def test_subscribe_receives_live_events(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, MockSandbox(), state,
                     executor_factory=_executor_factory,
                     llm=MockLLMClient([{"role": "assistant", "content": "done"}]))
    with tempfile.TemporaryDirectory() as d:
        pol_path = _write_open_policy(d)
        run = await mgr.submit("task", pol_path, "", max_steps=3)
        q = mgr.subscribe(run.run_id)
        for _ in range(100):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
        assert any(e.type == "run.ended" for e in received)


async def test_crash_marks_run_crashed(fake_redis):
    from cp.adapters.local_state import RedisStatePort

    class _BoomLLM:
        async def chat(self, messages, tools=None):
            raise RuntimeError("boom")

    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, MockSandbox(), state,
                     executor_factory=_executor_factory, llm=_BoomLLM())
    with tempfile.TemporaryDirectory() as d:
        pol_path = _write_open_policy(d)
        run = await mgr.submit("task", pol_path, "", max_steps=3)
        for _ in range(100):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        assert run.termination == "crashed"
        assert "boom" in run.final_answer
        assert any(e.type == "run.ended" for e in run.events)
