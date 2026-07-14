import json
import os
import tempfile
import time

from fastapi.testclient import TestClient

from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.adapters.local_state import RedisStatePort
from cp.llm.mock import MockLLMClient
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveRegistry
from cp.server.app import create_app
from cp.server.runmgr import RunManager
from cp.tools.tool import Registry


def _make_app(fake_redis):
    """构造测试 app:mock LLM + 允许 read 的临时 policy。"""
    sandbox = LocalSandboxExecutor(Registry())
    mgr = RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
                     executor_factory=lambda bus: PrimitiveExecutor(_prim_reg(), bus),
                     llm=MockLLMClient([{"role": "assistant", "content": "done"}]))
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "open.yaml"), "w") as f:
        f.write("permissions: []\nmax_steps: 5\n")
    san_dir = tempfile.mkdtemp()
    app = create_app(mgr, pol_dir, san_dir)
    return app, mgr


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


def test_list_policies(fake_redis):
    app, _ = _make_app(fake_redis)
    r = TestClient(app).get("/api/policies")
    assert r.status_code == 200
    assert "open.yaml" in r.json()


def test_list_sanitizations(fake_redis):
    app, _ = _make_app(fake_redis)
    r = TestClient(app).get("/api/sanitizations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_submit_run(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "do stuff", "policy": "open.yaml", "sanitization": ""})
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data and "session_id" in data
    _wait_ended(mgr.get(data["run_id"]))


def test_list_runs(fake_redis):
    app, _ = _make_app(fake_redis)
    client = TestClient(app)
    client.post("/api/runs", json={"task": "t1", "policy": "open.yaml", "sanitization": ""})
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_run_detail(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    rid = client.post("/api/runs", json={"task": "detail", "policy": "open.yaml", "sanitization": ""}).json()["run_id"]
    _wait_ended(mgr.get(rid))
    r = client.get(f"/api/runs?id={rid}")
    assert r.status_code == 200
    data = r.json()
    assert data["run"]["run_id"] == rid
    assert "events" in data


def test_get_run_not_found(fake_redis):
    app, _ = _make_app(fake_redis)
    r = TestClient(app).get("/api/runs?id=does-not-exist")
    assert r.status_code == 404


def test_ws_event_stream(fake_redis):
    """WS 连上后收到补播历史(含 run.ended)。"""
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    rid = client.post("/api/runs", json={"task": "ws test", "policy": "open.yaml", "sanitization": ""}).json()["run_id"]
    _wait_ended(mgr.get(rid))
    events = []
    with client.websocket_connect(f"/api/events?run_id={rid}") as ws:
        while True:
            msg = ws.receive_json()
            events.append(msg)
            if msg.get("type") == "run.ended":
                break
    types = [e["type"] for e in events]
    assert "run.ended" in types
    for e in events:
        assert e["run_id"] == rid


def test_resolve_real_policy_dir(fake_redis):
    """真实 examples/policies 目录解析(契约:返回 data_analyst.yaml)。"""
    sandbox = LocalSandboxExecutor(Registry())
    mgr = RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
                     executor_factory=lambda bus: PrimitiveExecutor(PrimitiveRegistry(), bus),
                     llm=MockLLMClient([{"role": "assistant", "content": "ok"}]))
    app = create_app(mgr, "examples/policies", "examples/sanitization")
    client = TestClient(app)
    assert "data_analyst.yaml" in client.get("/api/policies").json()
    assert "pii_rules.yaml" in client.get("/api/sanitizations").json()


def test_static_dir_mounted(fake_redis):
    """静态文件托管:根路径返回 index.html(若有)。"""
    sandbox = LocalSandboxExecutor(Registry())
    mgr = RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
                     executor_factory=lambda bus: PrimitiveExecutor(PrimitiveRegistry(), bus),
                     llm=MockLLMClient([{"role": "assistant", "content": "ok"}]))
    static_dir = tempfile.mkdtemp()
    with open(os.path.join(static_dir, "index.html"), "w") as f:
        f.write("<h1>AgentOS</h1>")
    app = create_app(mgr, tempfile.mkdtemp(), tempfile.mkdtemp(), static_dir=static_dir)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "AgentOS" in r.text


def test_cross_replica_run_visible_via_store(fake_redis):
    """副本 A 提交 run;副本 B(独立 RunManager,共享 redis)能读到 run + 事件。"""
    from cp.server.redis_store import RedisRunStore
    store = RedisRunStore(fake_redis)
    sandbox = LocalSandboxExecutor(Registry())

    def _mgr():
        return RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
                          executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                          llm=MockLLMClient([{"role": "assistant", "content": "done"}]),
                          run_store=store)

    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "p.yaml"), "w") as f:
        f.write("permissions: []\nmax_steps: 3\n")

    mgrA = _mgr()
    appA = create_app(mgrA, pol_dir, tempfile.mkdtemp(), run_store=store)
    rid = TestClient(appA).post("/api/runs", json={"task": "x", "policy": "p.yaml", "sanitization": ""}).json()["run_id"]
    _wait_ended(mgrA.get(rid))

    # 副本 B:全新 RunManager(进程内无此 run),共享 redis store
    mgrB = _mgr()
    appB = create_app(mgrB, pol_dir, tempfile.mkdtemp(), run_store=store)
    clientB = TestClient(appB)
    # list 能看到 A 的 run
    runs = clientB.get("/api/runs").json()
    assert any(r["run_id"] == rid for r in runs), "副本 B 看不到 A 的 run"
    # detail 能读到 A 的事件
    detail = clientB.get(f"/api/runs?id={rid}").json()
    assert detail["run"]["run_id"] == rid
    types = [e["type"] for e in detail["events"]]
    assert "run.ended" in types
