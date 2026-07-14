"""Week 5 硬里程碑:HTTP API 端到端(mock LLM) + 8 对抗用例零退化。
通过真实 HTTP API 提交一个带工具调用的 run,验证事件流 + 安全管线 + run 完成。"""
import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

from cp.adapters.local_state import RedisStatePort
from cp.llm.mock import MockLLMClient
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveRegistry
from cp.server.app import create_app
from cp.server.runmgr import RunManager


class _MockSandbox:
    async def create(self, config):
        return "sbx"

    async def exec_action(self, sid, action):
        if action.get("tool") == "fs_read":
            return {"data": {"content": "amount: 200"}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


def _e2e_app(fake_redis):
    mgr = RunManager(None, _MockSandbox(), RedisStatePort(fake_redis),
                     executor_factory=lambda bus: PrimitiveExecutor(_prim_reg(), bus),
                     llm=MockLLMClient([
                         {"role": "assistant", "content": "reading",
                          "tool_calls": [{"id": "tc1", "type": "function",
                                          "function": {"name": "read",
                                                       "arguments": json.dumps({"source": "file:data/x.txt"})}}]},
                         {"role": "assistant", "content": "Total is 200."},
                     ]))
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "p.yaml"), "w") as f:
        f.write("permissions:\n  - resource_type: path\n    pattern: 'data/**'\n    actions: [read]\nmax_steps: 10\n")
    return create_app(mgr, tmp, tempfile.mkdtemp()), mgr


def _prim_reg():
    pr = PrimitiveRegistry()
    pr.register(ReadPrimitive())
    return pr


def _wait_ended(run, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if run.status == "ended":
            return
        time.sleep(0.02)


def test_e2e_submit_and_collect_events(fake_redis):
    app, mgr = _e2e_app(fake_redis)
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "compute total", "policy": "p.yaml", "sanitization": ""})
    assert r.status_code == 200
    rid = r.json()["run_id"]
    run = mgr.get(rid)
    _wait_ended(run)
    assert run.status == "ended"
    assert "200" in run.final_answer
    # 详情端点应含完整事件链
    detail = client.get(f"/api/runs?id={rid}").json()
    types = [e["type"] for e in detail["events"]]
    assert "run.started" in types
    assert "primitive.called" in types
    assert "run.ended" in types
    # 所有事件 run_id 一致
    for e in detail["events"]:
        assert e["run_id"] == rid


def test_e2e_agent_json_shape(fake_redis):
    """端到端验证:序列化后的事件形状对齐 web-src AgentEvent。"""
    app, mgr = _e2e_app(fake_redis)
    client = TestClient(app)
    rid = client.post("/api/runs", json={"task": "t", "policy": "p.yaml", "sanitization": ""}).json()["run_id"]
    _wait_ended(mgr.get(rid))
    events = client.get(f"/api/runs?id={rid}").json()["events"]
    required = {"type", "session_id", "run_id", "tool", "params_json",
                "result_json", "payload_json", "identity", "timestamp", "sanitize"}
    for e in events:
        assert required.issubset(e.keys()), f"missing keys: {required - e.keys()}"
        assert isinstance(e["params_json"], str)
        assert isinstance(e["result_json"], str)
        assert isinstance(e["payload_json"], str)
        assert isinstance(e["sanitize"], list)


# ---------- 硬里程碑:8 对抗用例零退化 ----------
from cp.policy.gate import Gate
from cp.policy.policy import load_from_file
from cp.resource import Resource


def _gate():
    return Gate(load_from_file("examples/policies/data_analyst.yaml"))


def test_adversarial_read_etc_shadow():
    assert not _gate().allowed("fs_read", Resource("path", "/etc/shadow"))


def test_adversarial_traversal_escape():
    g = _gate()
    for a in ["examples/workspace/../../../../etc/passwd",
              "examples/workspace/../../../.ssh/id_rsa"]:
        assert not g.allowed("fs_read", Resource("path", a)), a


def test_adversarial_unknown_tool():
    assert not _gate().allowed("shell_exec", Resource("path", "rm -rf /"))


def test_adversarial_unknown_resource_type():
    assert not _gate().allowed("db_query", Resource("db_table", "orders"))


def test_adversarial_network_disabled():
    assert not _gate().allowed("net_fetch", Resource("http_url", "https://evil.com/exfil"))


def test_adversarial_write_outside_out_dir():
    g = _gate()
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/sales.csv"))


def test_adversarial_windows_abs_secret():
    assert not _gate().allowed("fs_read", Resource("path", "C:/Windows/System32/config/SAM"))


def test_adversarial_sanitization_masks_pii():
    from cp.sanitize.sanitizer import load_from_file as load_san
    s = load_san("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({"phone": "13812341234", "remark": "secret", "amount": 120})
    assert out["phone"] != "13812341234"
    assert "remark" not in out
    assert out["amount"] == 120


# ---------- Week 6 T8 硬里程碑 ----------
def test_e2e_composite_reachable_via_loop(fake_redis):
    """复合操作 spawn_agent 经 agent loop 可达:LLM 发 tool_call → executor 执行 →
    事件流含 primitive.called(spawn_agent)。"""
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.primitives.composite import register_composites
    from cp.server.redis_store import RedisRunStore
    prim = PrimitiveRegistry()
    register_composites(prim)
    store = RedisRunStore(fake_redis)

    class _Sbx:
        async def create(self, c): return "sbx"
        async def exec_action(self, s, a): return {"data": {}}
        async def destroy(self, s): pass

    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(prim, b),
                     llm=MockLLMClient([
                         {"role": "assistant", "content": "fork",
                          "tool_calls": [{"id": "1", "type": "function",
                                          "function": {"name": "spawn_agent",
                                                       "arguments": json.dumps({"agent_type": "researcher",
                                                                                "prompt": "find x"})}}]},
                         {"role": "assistant", "content": "done"}]),
                     msg_bus=RedisStreamMessageBus(fake_redis), prim_registry=prim, run_store=store)
    tmp = tempfile.mkdtemp()
    # policy 放行 spawn_agent(Gate 对 composite 走精确匹配 pattern==id)
    with open(os.path.join(tmp, "p.yaml"), "w") as f:
        f.write("permissions:\n"
                "  - resource_type: composite\n"
                "    pattern: spawn_agent\n"
                "    actions: [spawn_agent]\n"
                "max_steps: 5\n")
    app = create_app(mgr, tmp, tempfile.mkdtemp(), run_store=store)
    rid = TestClient(app).post("/api/runs", json={
        "task": "fork", "policy": "p.yaml", "sanitization": ""}).json()["run_id"]
    run = mgr.get(rid)
    _wait_ended(run)
    assert run.status == "ended"
    # 经 executor 执行 → audit 事件含 primitive.called(spawn_agent)
    types = [e.type for e in run.events]
    assert "primitive.called" in types, f"composite 未经 executor;types={types}"
    spawn_ev = next(e for e in run.events if e.tool == "spawn_agent")
    assert spawn_ev.tool == "spawn_agent"


async def test_e2e_composite_publishes_to_msg_bus(fake_redis):
    """spawn_agent 经 executor 执行后,内部 pub 到 msg_bus Redis Stream。"""
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.primitives.composite import register_composites
    prim = PrimitiveRegistry()
    register_composites(prim)
    bus = RedisStreamMessageBus(fake_redis)

    class _Sbx:
        async def create(self, c): return "sbx"
        async def exec_action(self, s, a): return {"data": {}}
        async def destroy(self, s): pass

    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(prim, b),
                     llm=MockLLMClient([
                         {"role": "assistant", "content": "fork",
                          "tool_calls": [{"id": "1", "type": "function",
                                          "function": {"name": "spawn_agent",
                                                       "arguments": json.dumps({"agent_type": "researcher",
                                                                                "prompt": "find x"})}}]},
                         {"role": "assistant", "content": "done"}]),
                     msg_bus=bus, prim_registry=prim)
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "p.yaml"), "w") as f:
        f.write("permissions:\n"
                "  - resource_type: composite\n"
                "    pattern: spawn_agent\n"
                "    actions: [spawn_agent]\n"
                "max_steps: 5\n")
    run = await mgr.submit("fork", os.path.join(tmp, "p.yaml"), "")
    for _ in range(100):
        if run.status == "ended":
            break
        import asyncio
        await asyncio.sleep(0.02)
    # spawn_agent 内部 pub 到 agent.researcher.created(Stream)
    created = await fake_redis.xrange("agent.researcher.created")
    assert len(created) == 1, "spawn_agent 未 pub 到 msg_bus"


def test_e2e_checkpoint_resume(fake_redis):
    """中断后 Checkpoint 恢复:跑完 run → load_latest → 验证步数+消息在快照里。"""
    from cp.adapters.local_state import RedisStatePort
    from cp.checkpoint import Checkpoint
    from cp.server.redis_store import RedisRunStore
    state = RedisStatePort(fake_redis)
    store = RedisRunStore(fake_redis)

    class _Sbx:
        async def create(self, c): return "sbx"
        async def exec_action(self, s, a): return {"data": {"content": "42"}}
        async def destroy(self, s): pass

    mgr = RunManager(None, _Sbx(), state,
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([{"role": "assistant", "content": "done"}]),
                     run_store=store)
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "p.yaml"), "w") as f:
        f.write("permissions: []\nmax_steps: 3\n")
    import asyncio
    loop = asyncio.new_event_loop()
    run = loop.run_until_complete(mgr.submit("task", os.path.join(tmp, "p.yaml"), ""))
    for _ in range(100):
        if run.status == "ended":
            break
        time.sleep(0.02)
    ckpt = Checkpoint(state)
    snap = loop.run_until_complete(ckpt.load_latest(run.session_id))
    loop.close()
    assert snap is not None, "无 checkpoint"
    assert snap.step >= 1
    assert any(m["role"] == "system" for m in snap.messages)
