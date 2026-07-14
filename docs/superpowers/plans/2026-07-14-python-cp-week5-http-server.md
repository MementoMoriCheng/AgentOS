# Week 5 — HTTP 服务层 + 真实 LLM 端到端 + Web 控制台对接

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 给 `cp/` 加上 FastAPI HTTP 服务层(复刻旧 gateway 的 API 契约,前端零改)+ Run Manager(异步 run 生命周期 + 事件收集)+ WebSocket 事件流(补播历史 + 实时推送)+ 静态前端托管 + CLI 入口,让系统从"库 + 测试"变成"能 demo 的产品"。

**Architecture:** FastAPI 服务复刻旧 gateway 的端点契约(`POST /api/runs`、`GET /api/runs`、`GET /api/policies`、`WS /api/events?run_id=X`),这样 `web-src/` 前端零改动对接。RunManager 用 asyncio 管 run 生命周期:每个 run 一个 InProcess bus 收集事件,后台 task 跑 `run_agent_loop`,WS 端点补播历史 + 实时推送。事件序列化器把 `cp/Event` 转成前端的 `AgentEvent` JSON 形状。静态文件托管 `web-src/dist`(若已构建)。

**Tech Stack:** FastAPI / uvicorn / httpx(TestClient)/ websockets / fakeredis / pytest-asyncio

**硬里程碑:** T7 的 HTTP API 端到端测试(mock LLM)跑通 + 8 对抗用例全绿 + 全回归。

---

## API 契约(复刻旧 gateway,前端零改)

来自 `web-src/src/lib/api.ts` + `gateway/internal/api/handlers.go`:

| 端点 | 方法 | 入参 | 出参 |
|------|------|------|------|
| `/api/runs` | POST | `{task, policy, sanitization}` | `{run_id, session_id}` |
| `/api/runs` | GET | — | `[{run_id, session_id, status, task, started_at}]` |
| `/api/runs?id=X` | GET | query `id` | `{run:{run_id,...}, events:[...]}` |
| `/api/policies` | GET | — | `["data_analyst.yaml", ...]` |
| `/api/sanitizations` | GET | — | `["pii_rules.yaml", ...]` |
| `/api/events?run_id=X` | WS | query `run_id` | 流:`AgentEvent` JSON |

AgentEvent JSON 形状(`api.ts`):
```json
{"type":"...", "session_id":"...", "run_id":"...", "tool":"...",
 "params_json":"{}", "result_json":"{}", "payload_json":"{}",
 "identity":"...", "timestamp":0,
 "sanitize":[{"field":"...", "strategy":"..."}]}
```

---

## 文件结构(Week 5 新增)

```
cp/
├── server/                 # 【新】HTTP 服务层
│   ├── __init__.py
│   ├── runmgr.py           # RunManager(异步 run 生命周期 + 事件收集)
│   ├── serialize.py        # cp/Event → AgentEvent JSON
│   ├── app.py              # FastAPI app(路由 + WS + 静态文件)
│   └── cli.py              # python -m cp.server.cli serve
└── tests/
    ├── test_serialize.py
    ├── test_runmgr.py
    └── test_api.py         # HTTP + WS 端到端(TestClient + fakeredis)
```

---

## 任务总览

| # | 任务 | 验收标准 |
|---|------|---------|
| T1 | 事件序列化器 + run_id 穿透 | Event→AgentEvent JSON 正确;run_id 进 PrimitiveContext/事件 |
| T2 | RunManager(异步生命周期) | submit→后台跑→ended;事件收集到 ring |
| T3 | FastAPI HTTP 端点(POST/GET runs, policies) | TestClient 测:提交/列表/详情 |
| T4 | WebSocket 事件流(补播+实时) | TestClient WS 测:连上后收历史+实时事件 |
| T5 | 静态文件托管 + policy 路径解析 | /api/policies 列 examples/;根路径托管 dist |
| T6 | CLI 入口(python -m cp.server.cli serve) | uvicorn 启动;--help 可用 |
| T7 | HTTP API 端到端(mock LLM)+ 对抗回归(硬里程碑) | 提交 run→收事件→ended;8 对抗全绿 |
| T8 | 真实 LLM 端到端(opt-in 集成) | 有效 key 时真实 DeepSeek 跑通;无 key skip |
| T9 | 最终验证 + push | 全回归绿;前端构建说明 |

---

## Task 1: 事件序列化器 + run_id 穿透

**Files:**
- Create: `cp/server/__init__.py` (empty)
- Create: `cp/server/serialize.py`
- Modify: `cp/primitives/registry.py`(PrimitiveContext 加 run_id)
- Modify: `cp/primitives/executor.py`(事件加 run_id)
- Modify: `cp/pipeline/pipeline.py`(事件加 run_id)
- Test: `cp/tests/test_serialize.py`

### `cp/server/serialize.py`:
```python
import json
from cp.eventbus.bus import Event


def event_to_agent_json(e: Event) -> dict:
    """把 cp/Event 转成前端 AgentEvent JSON 形状。
    params/result/payload 序列化成 JSON 字符串(前端约定)。"""
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
```

### Modify PrimitiveContext — 加 run_id 字段:
`cp/primitives/registry.py` 的 `PrimitiveContext.__init__`:
```python
class PrimitiveContext:
    def __init__(self, session=None, sandbox_id="", sandbox=None, bus=None, state=None, run_id=""):
        self.session = session
        self.sandbox_id = sandbox_id
        self.sandbox = sandbox
        self.bus = bus
        self.state = state
        self.run_id = run_id  # 【新】当前 run id,事件用它关联 run
```

### Modify PrimitiveExecutor — 事件带 run_id:
`cp/primitives/executor.py` 的所有 `Event(...)` 构造加 `run_id=ctx.run_id`。即把:
```python
await self.bus.publish(Event(type="primitive.denied", session_id=sess.id, tool=prim_name, params=params))
```
改成:
```python
await self.bus.publish(Event(type="primitive.denied", session_id=sess.id, run_id=ctx.run_id, tool=prim_name, params=params))
```
对 executor 里的 5 处 publish 全部加 `run_id=ctx.run_id`(primitive.denied×2, quota.exceeded, primitive.errored, primitive.called)。

### Test `cp/tests/test_serialize.py`:
```python
from cp.eventbus.bus import Event, FieldSanitization
from cp.server.serialize import event_to_agent_json


def test_basic_event_serialization():
    e = Event(type="primitive.called", session_id="s1", run_id="r1", tool="read")
    out = event_to_agent_json(e)
    assert out["type"] == "primitive.called"
    assert out["run_id"] == "r1"
    assert out["params_json"] == "{}"
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
```

- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_serialize.py -v` → 3 passed
- [ ] 全回归确认无破坏(现有测试的 PrimitiveContext 调用不受影响——run_id 有默认值 "")
- [ ] 提交 `git add -A && git commit -m "feat(cp): event serializer + run_id threading through context/events"`

---

## Task 2: RunManager(异步生命周期 + 事件收集)

**Files:**
- Create: `cp/server/runmgr.py`
- Test: `cp/tests/test_runmgr.py`

### `cp/server/runmgr.py`:
```python
"""异步 Run Manager:管理 run 生命周期 + 事件收集。
每个 run 一个 InProcess bus 收集事件;后台 asyncio task 跑 agent loop。"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from cp.audit.ledger import Ledger
from cp.eventbus.bus import Event, InProcess
from cp.policy.policy import Policy, load_from_file
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.registry import PrimitiveContext
from cp.sanitize.sanitizer import load_from_file as load_san, Sanitizer
from cp.session.session import Session
from cp.agent_loop import run_agent_loop
from cp.tools.tool import Registry


@dataclass
class Run:
    run_id: str
    session_id: str
    task: str
    status: str = "running"  # running | ended
    started_at: float = field(default_factory=time.time)
    events: List[Event] = field(default_factory=list)
    final_answer: str = ""
    termination: str = ""
    _subscribers: List[asyncio.Queue] = field(default_factory=list)


class RunManager:
    """管理 run:建 session → 后台跑 agent loop → 收集事件 → 标 ended。"""

    def __init__(self, registry: Registry, sandbox, state, audit_dir: str = "./audit"):
        self.registry = registry
        self.sandbox = sandbox
        self.state = state
        self.audit_dir = audit_dir
        self._runs: Dict[str, Run] = {}
        self._mu = asyncio.Lock()

    async def submit(self, task: str, policy_path: str, sanitization_path: str,
                     executor_factory: Callable, llm, max_steps: int = 20) -> Run:
        """提交 run。executor_factory: (bus) -> PrimitiveExecutor。"""
        pol = load_from_file(policy_path)
        san = load_san(sanitization_path) if sanitization_path else Sanitizer.new_from_rules([])
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

        ledger = Ledger(f"{self.audit_dir}/{session_id}.log")
        sess = Session.new(session_id, "local", pol, san, ledger)

        bus = InProcess()
        sandbox_id = await self.sandbox.create({"workspace": "."})

        executor = executor_factory(bus)
        ctx = PrimitiveContext(
            session=sess, sandbox_id=sandbox_id, sandbox=self.sandbox,
            bus=None, state=self.state, run_id=run_id,
        )

        run = Run(run_id=run_id, session_id=session_id, task=task)
        # 事件收集器:订阅 bus,追加到 run.events,推给 WS 订阅者
        async def _collector(e: Event):
            run.events.append(e)
            for q in list(run._subscribers):
                try:
                    q.put_nowait(e)
                except asyncio.QueueFull:
                    pass
        bus.subscribe(_collector)

        async with self._mu:
            self._runs[run_id] = run

        # 发布 run.started
        bus.subscribe(_collector)  # 已订阅
        await bus.publish(Event(type="run.started", session_id=session_id, run_id=run_id,
                                payload={"task": task, "max_steps": max_steps}))

        # 后台跑 agent loop
        asyncio.create_task(self._run_agent(run, sess, ctx, executor, llm, bus, max_steps))
        return run

    async def _run_agent(self, run: Run, sess, ctx, executor, llm, bus, max_steps):
        try:
            result = await run_agent_loop(
                run.task, llm, executor, sess, ctx, [], max_steps,
            )
            run.final_answer = result["final_answer"]
            run.termination = result["termination"]
            await bus.publish(Event(
                type="run.ended", session_id=run.session_id, run_id=run.run_id,
                payload={"termination": run.termination, "final_answer": run.final_answer},
            ))
        except Exception as e:
            run.termination = "crashed"
            run.final_answer = f"error: {e}"
            await bus.publish(Event(
                type="run.ended", session_id=run.session_id, run_id=run.run_id,
                payload={"termination": "crashed", "final_answer": run.final_answer},
            ))
        finally:
            run.status = "ended"

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def list_runs(self) -> List[Run]:
        return list(self._runs.values())

    def subscribe(self, run_id: str) -> asyncio.Queue:
        """订阅某 run 的实时事件。返回 Queue。"""
        run = self._runs.get(run_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        if run is not None:
            run._subscribers.append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue):
        run = self._runs.get(run_id)
        if run and q in run._subscribers:
            run._subscribers.remove(q)
```

### Test `cp/tests/test_runmgr.py`:
```python
import asyncio
import json
import os
import tempfile

from cp.agent_loop import run_agent_loop  # noqa (used by runmgr)
from cp.eventbus.bus import InProcess
from cp.llm.mock import MockLLMClient
from cp.policy.policy import load_from_file
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.sanitize.sanitizer import load_from_file as load_san
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


async def test_submit_creates_run_and_completes(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(PrimitiveRegistry(), MockSandbox(), state)
    # policy/sanitization 用真实 examples(但 gate 要允许 read)
    # 为了测试,我们造一个允许 read 的临时 policy
    with tempfile.TemporaryDirectory() as d:
        pol_path = os.path.join(d, "p.yaml")
        with open(pol_path, "w") as f:
            f.write("permissions:\n  - resource_type: path\n    pattern: '**'\n    actions: [read]\nmax_steps: 10\n")
        llm = MockLLMClient([
            {"role": "assistant", "content": "let me read",
             "tool_calls": [{"id": "tc1", "type": "function",
                             "function": {"name": "read", "arguments": json.dumps({"source": "file:data/x.txt"})}}]},
            {"role": "assistant", "content": "The answer is 42."},
        ])
        run = await mgr.submit("read and answer", pol_path, "", _executor_factory, llm, max_steps=5)
        assert run.run_id.startswith("run-")
        # 等后台完成
        for _ in range(50):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        assert run.status == "ended"
        assert "42" in run.final_answer
        # 事件应有 run.started + primitive.called + run.ended
        types = [e.type for e in run.events]
        assert "run.started" in types
        assert "run.ended" in types


async def test_events_carry_run_id(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(PrimitiveRegistry(), MockSandbox(), state)
    with tempfile.TemporaryDirectory() as d:
        pol_path = os.path.join(d, "p.yaml")
        with open(pol_path, "w") as f:
            f.write("permissions:\n  - resource_type: path\n    pattern: '**'\n    actions: [read]\nmax_steps: 10\n")
        llm = MockLLMClient([{"role": "assistant", "content": "done right away"}])
        run = await mgr.submit("task", pol_path, "", _executor_factory, llm, max_steps=3)
        for _ in range(50):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        for e in run.events:
            assert e.run_id == run.run_id, f"event {e.type} missing run_id"


async def test_subscribe_receives_live_events(fake_redis):
    from cp.adapters.local_state import RedisStatePort
    state = RedisStatePort(fake_redis)
    mgr = RunManager(PrimitiveRegistry(), MockSandbox(), state)
    with tempfile.TemporaryDirectory() as d:
        pol_path = os.path.join(d, "p.yaml")
        with open(pol_path, "w") as f:
            f.write("permissions: []\nmax_steps: 5\n")
        llm = MockLLMClient([{"role": "assistant", "content": "done"}])
        run = await mgr.submit("task", pol_path, "", _executor_factory, llm, max_steps=3)
        q = mgr.subscribe(run.run_id)
        for _ in range(50):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
        # queue 里应有 run.ended(订阅后产生的事件)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
        # 至少有 run.ended(因为 subscribe 可能在 run.started 之后)
        assert any(e.type == "run.ended" for e in received)
```

- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_runmgr.py -v` → 3 passed
- [ ] 提交 `git add cp/server/runmgr.py cp/tests/test_runmgr.py && git commit -m "feat(cp): async RunManager (lifecycle + event collection)"`

---

## Task 3: FastAPI HTTP 端点

**Files:**
- Create: `cp/server/app.py`
- Test: `cp/tests/test_api.py`

### `cp/server/app.py`:
```python
"""FastAPI 应用:复刻旧 gateway 的 API 契约,前端零改对接。"""
import os
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cp.server.runmgr import RunManager
from cp.server.serialize import event_to_agent_json


def create_app(mgr: RunManager, policy_dir: str, sanitization_dir: str,
               static_dir: str = None) -> FastAPI:
    app = FastAPI(title="AgentOS Control Plane")

    @app.get("/api/policies")
    async def list_policies():
        return _scan_yaml(policy_dir)

    @app.get("/api/sanitizations")
    async def list_sanitizations():
        return _scan_yaml(sanitization_dir)

    @app.get("/api/runs")
    async def list_runs(id: str = None):
        if id:
            run = mgr.get(id)
            if run is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return {
                "run": {
                    "run_id": run.run_id, "session_id": run.session_id,
                    "status": run.status, "task": run.task,
                    "started_at": run.started_at,
                },
                "events": [event_to_agent_json(e) for e in run.events],
            }
        return [
            {"run_id": r.run_id, "session_id": r.session_id, "status": r.status,
             "task": r.task, "started_at": r.started_at}
            for r in mgr.list_runs()
        ]

    @app.post("/api/runs")
    async def submit_run(body: dict):
        task = body.get("task", "")
        policy = _resolve(body.get("policy", ""), policy_dir)
        sanitization = _resolve(body.get("sanitization", ""), sanitization_dir)
        run = await mgr.submit(
            task, policy, sanitization,
            mgr._executor_factory, mgr._llm, max_steps=20,
        )
        return {"run_id": run.run_id, "session_id": run.session_id}

    @app.websocket("/api/events")
    async def events_ws(ws: WebSocket):
        await ws.accept()
        run_id = ws.query_params.get("run_id", "")
        # 补播历史
        run = mgr.get(run_id)
        if run is not None:
            for e in run.events:
                await ws.send_json(event_to_agent_json(e))
            if run.status == "ended":
                await ws.close()
                return
        # 实时推送
        q = mgr.subscribe(run_id)
        try:
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=30.0)
                    await ws.send_json(event_to_agent_json(e))
                    if e.type == "run.ended":
                        break
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass
        finally:
            mgr.unsubscribe(run_id, q)
            await ws.close()

    # 静态前端(如果 dist 已构建)
    if static_dir and os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def _scan_yaml(directory: str) -> List[str]:
    if not directory or not os.path.isdir(directory):
        return []
    out = []
    for f in sorted(os.listdir(directory)):
        if f.endswith(".yaml") or f.endswith(".yml"):
            out.append(f)
    return out


def _resolve(name: str, directory: str) -> str:
    """把文件名解析成完整路径(若在 directory 内)。"""
    if not name:
        return name
    if os.path.sep in name or "/" in name or os.path.isabs(name):
        return name  # 已是路径
    full = os.path.join(directory, name)
    return full if os.path.exists(full) else name


import asyncio  # noqa: E402 (放最后避免循环)
```

### Test `cp/tests/test_api.py`:
```python
import asyncio
import json
import os
import tempfile

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
    """构造一个测试 app(mock LLM,允许 read 的 policy)。"""
    reg = Registry()
    sandbox = LocalSandboxExecutor(reg)
    state = RedisStatePort(fake_redis)
    mgr = RunManager(reg, sandbox, state)
    # 注入 executor factory + llm
    def ex_factory(bus):
        pr = PrimitiveRegistry()
        pr.register(ReadPrimitive())
        return PrimitiveExecutor(pr, bus)
    mgr._executor_factory = ex_factory
    mgr._llm = MockLLMClient([{"role": "assistant", "content": "done"}])
    # 临时 policy 目录
    tmpdir = tempfile.mkdtemp()
    pol_path = os.path.join(tmpdir, "open.yaml")
    with open(pol_path, "w") as f:
        f.write("permissions: []\nmax_steps: 5\n")
    san_dir = tempfile.mkdtemp()
    app = create_app(mgr, tmpdir, san_dir)
    return app, mgr


def test_list_policies(fake_redis):
    app, _ = _make_app(fake_redis)
    client = TestClient(app)
    r = client.get("/api/policies")
    assert r.status_code == 200
    assert "open.yaml" in r.json()


def test_list_sanitizations(fake_redis):
    app, _ = _make_app(fake_redis)
    client = TestClient(app)
    r = client.get("/api/sanitizations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_submit_run(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "do stuff", "policy": "open.yaml", "sanitization": ""})
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data and "session_id" in data
    # 等 run 结束
    run = mgr.get(data["run_id"])
    for _ in range(50):
        if run.status == "ended":
            break
        import time; time.sleep(0.02)


def test_list_runs(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    client.post("/api/runs", json={"task": "t1", "policy": "open.yaml", "sanitization": ""})
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_run_detail(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    resp = client.post("/api/runs", json={"task": "detail", "policy": "open.yaml", "sanitization": ""})
    rid = resp.json()["run_id"]
    run = mgr.get(rid)
    for _ in range(50):
        if run.status == "ended":
            break
        import time; time.sleep(0.02)
    r = client.get(f"/api/runs?id={rid}")
    assert r.status_code == 200
    data = r.json()
    assert data["run"]["run_id"] == rid
    assert "events" in data
```

- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_api.py -v` → 5 passed
- [ ] 提交 `git add cp/server/app.py cp/tests/test_api.py && git commit -m "feat(cp): FastAPI HTTP endpoints (runs/policies/sanitizations)"`

---

## Task 4: WebSocket 事件流

已在 T3 的 `app.py` 里实现 `events_ws`。用 TestClient 测 WS。

在 `cp/tests/test_api.py` 追加:
```python
def test_ws_event_stream(fake_redis):
    app, mgr = _make_app(fake_redis)
    client = TestClient(app)
    # 先提交 run
    resp = client.post("/api/runs", json={"task": "ws test", "policy": "open.yaml", "sanitization": ""})
    rid = resp.json()["run_id"]
    run = mgr.get(rid)
    # 等 run 结束
    for _ in range(50):
        if run.status == "ended":
            break
        import time; time.sleep(0.02)
    # 连 WS,应收到补播的历史事件(含 run.started + run.ended)
    with client.websocket_connect(f"/api/events?run_id={rid}") as ws:
        events = []
        try:
            while True:
                msg = ws.receive_json()
                events.append(msg)
                if msg.get("type") == "run.ended":
                    break
        except Exception:
            pass
        types = [e["type"] for e in events]
        assert "run.ended" in types
        for e in events:
            assert e["run_id"] == rid
```

- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_api.py::test_ws_event_stream -v` → 1 passed
- [ ] 提交 `git add cp/tests/test_api.py && git commit -m "test(cp): WebSocket event stream (replay + live)"`

---

## Task 5: policy 路径解析 + 静态文件

已在 T3 实现 `_resolve` + `_scan_yaml` + StaticFiles 挂载。验证:
- `/api/policies` 列出 `examples/policies/` 的 yaml
- 根路径托管 `web-src/dist`(若存在)

测试:用真实 `examples/policies` 目录构造 app,确认返回 `data_analyst.yaml`。

在 `test_api.py` 追加:
```python
def test_resolve_real_policy_dir(fake_redis):
    app, _ = _make_app(fake_redis)
    # 重建 app 指向真实 examples
    from cp.server.app import create_app
    reg = Registry()
    mgr = RunManager(reg, LocalSandboxExecutor(reg), RedisStatePort(fake_redis))
    mgr._executor_factory = lambda bus: PrimitiveExecutor(PrimitiveRegistry(), bus)
    mgr._llm = MockLLMClient([{"role": "assistant", "content": "ok"}])
    app2 = create_app(mgr, "examples/policies", "examples/sanitization")
    client = TestClient(app2)
    r = client.get("/api/policies")
    assert "data_analyst.yaml" in r.json()
    r2 = client.get("/api/sanitizations")
    assert "pii_rules.yaml" in r2.json()
```

- [ ] 跑 → passed
- [ ] 提交 `git add cp/tests/test_api.py && git commit -m "test(cp): policy/sanitization resolution from examples/"`

---

## Task 6: CLI 入口

**Files:**
- Create: `cp/server/cli.py`

### `cp/server/cli.py`:
```python
"""CLI 入口:python -m cp.server.cli serve [--host] [--port] [--redis-url]"""
import argparse
import asyncio

from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.adapters.local_state import RedisStatePort
from cp.compose import build_control_plane
from cp.llm.mock import MockLLMClient
from cp.primitives.executor import PrimitiveExecutor
from cp.server.app import create_app
from cp.server.runmgr import RunManager
from cp.tools.tool import Registry


def _make_redis(url: str):
    if url:
        import redis.asyncio as aioredis
        return aioredis.from_url(url)
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis()


def serve(host: str = "127.0.0.1", port: int = 8080, redis_url: str = "",
          policy_dir: str = "examples/policies", sanitization_dir: str = "examples/sanitization",
          static_dir: str = "web-src/dist", llm_mode: str = "mock"):
    import uvicorn
    redis = _make_redis(redis_url)
    cp = build_control_plane(redis)
    reg = cp["registry"]
    mgr = RunManager(reg, cp["sandbox"], cp["state"])
    # executor factory + llm
    def ex_factory(bus):
        return PrimitiveExecutor(cp["prim_registry"], bus)
    mgr._executor_factory = ex_factory
    if llm_mode == "real":
        from cp.llm.deepseek import AsyncDeepSeekClient
        mgr._llm = AsyncDeepSeekClient()
    else:
        mgr._llm = MockLLMClient([{"role": "assistant", "content": "[server mock] done"}])
    app = create_app(mgr, policy_dir, sanitization_dir, static_dir)
    print(f"AgentOS 控制面启动: http://{host}:{port} (llm={llm_mode})")
    uvicorn.run(app, host=host, port=port)


def main():
    p = argparse.ArgumentParser(description="AgentOS control plane server")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="启动 HTTP 服务")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--redis-url", default="", help="空=fakeredis")
    s.add_argument("--policy-dir", default="examples/policies")
    s.add_argument("--sanitization-dir", default="examples/sanitization")
    s.add_argument("--static-dir", default="web-src/dist")
    s.add_argument("--llm", default="mock", choices=["mock", "real"])
    args = p.parse_args()
    if args.cmd == "serve":
        serve(args.host, args.port, args.redis_url, args.policy_dir,
              args.sanitization_dir, args.static_dir, args.llm)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
```

- [ ] 验证:`conda run -n agentos python -m cp.server.cli --help` 应输出 serve 帮助
- [ ] 提交 `git add cp/server/cli.py && git commit -m "feat(cp): CLI entry (python -m cp.server.cli serve)"`

---

## Task 7: HTTP API 端到端(mock LLM)+ 对抗回归(硬里程碑)

**Files:**
- Create: `cp/tests/test_api_e2e.py`

端到端:通过 HTTP API 提交一个真实数据分析任务(mock LLM 脚本),验证事件流 + 安全管线 + run 完成。

```python
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
    reg = Registry()
    sandbox = _MockSandbox()
    mgr = RunManager(reg, sandbox, RedisStatePort(fake_redis))
    def ex_factory(bus):
        pr = PrimitiveRegistry()
        pr.register(ReadPrimitive())
        return PrimitiveExecutor(pr, bus)
    mgr._executor_factory = ex_factory
    mgr._llm = MockLLMClient([
        {"role": "assistant", "content": "reading",
         "tool_calls": [{"id": "tc1", "type": "function",
                         "function": {"name": "read", "arguments": json.dumps({"source": "file:data/x.txt"})}}]},
        {"role": "assistant", "content": "Total is 200."},
    ])
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "p.yaml"), "w") as f:
        f.write("permissions:\n  - resource_type: path\n    pattern: 'data/**'\n    actions: [read]\nmax_steps: 10\n")
    return create_app(mgr, tmp, tempfile.mkdtemp()), mgr


def test_e2e_submit_and_collect_events(fake_redis):
    app, mgr = _e2e_app(fake_redis)
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "compute total", "policy": "p.yaml", "sanitization": ""})
    assert r.status_code == 200
    rid = r.json()["run_id"]
    run = mgr.get(rid)
    for _ in range(100):
        if run.status == "ended":
            break
        time.sleep(0.02)
    assert run.status == "ended"
    assert "200" in run.final_answer
    # 详情端点应有事件
    detail = client.get(f"/api/runs?id={rid}").json()
    types = [e["type"] for e in detail["events"]]
    assert "run.started" in types
    assert "primitive.called" in types
    assert "run.ended" in types


async def test_adversarial_regression():
    """硬里程碑:对抗用例仍全绿。"""
    from cp.policy.gate import Gate
    from cp.policy.policy import load_from_file
    from cp.resource import Resource
    g = Gate(load_from_file("examples/policies/data_analyst.yaml"))
    assert not g.allowed("fs_read", Resource("path", "/etc/shadow"))
    assert g.allowed("fs_read", Resource("path", "examples/workspace/sales.csv"))
```

- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_api_e2e.py -v` → 2 passed
- [ ] 跑对抗 `conda run -n agentos python -m pytest cp/tests/adversarial/ -v` → 8 passed(硬里程碑)
- [ ] 全回归 `conda run -n agentos python -m pytest cp/ -v`
- [ ] 提交 `git add cp/tests/test_api_e2e.py && git commit -m "test(cp): HTTP API e2e (mock LLM) + adversarial regression"`

---

## Task 8: 真实 LLM 端到端(opt-in)

**Files:**
- Modify: `cp/tests/test_deepseek.py` 追加(或新建 `cp/tests/test_real_e2e.py`)

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("RUN_INTEGRATION")),
    reason="integration: set DEEPSEEK_API_KEY + RUN_INTEGRATION=1",
)


async def test_real_llm_agent_loop():
    """真实 DeepSeek 跑 Agent Loop(无工具,单轮问答)。"""
    from cp.llm.deepseek import AsyncDeepSeekClient
    from cp.agent_loop import run_agent_loop
    from cp.audit.ledger import Ledger
    from cp.policy.policy import Policy
    from cp.sanitize.sanitizer import Sanitizer
    from cp.session.session import Session
    import tempfile
    llm = AsyncDeepSeekClient()
    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local",
                           Policy(permissions=[], max_steps=3, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        result = await run_agent_loop("Reply with exactly: hello world", llm, None, sess, None, [])
        assert result["termination"] == "completed"
        assert "hello" in result["final_answer"].lower()
```

- [ ] 跑(默认 skip):`conda run -n agentos python -m pytest cp/tests/test_real_e2e.py -v` → 1 skipped
- [ ] 提交 `git add cp/tests/test_real_e2e.py && git commit -m "test(cp): real DeepSeek e2e (opt-in integration)"`

---

## Task 9: 最终验证 + push

- [ ] 全回归:`conda run -n agentos python -m pytest cp/ -v` → 全绿
- [ ] 对抗:8 passed
- [ ] 零 TODO/FIXME
- [ ] 手动验证 CLI:`conda run -n agentos python -m cp.server.cli --help`
- [ ] 更新 README(标注 cp/ 是当前实现,kernel/gateway 是 legacy)
- [ ] `git push`

---

## Week 5 完成判据

- [ ] `pytest cp/` 全绿
- [ ] HTTP API(POST/GET runs, policies, sanitizations)可工作
- [ ] WebSocket 事件流(补播历史 + 实时推送)可工作
- [ ] CLI `python -m cp.server.cli serve` 可启动
- [ ] 端到端(mock LLM)经 HTTP API 跑通
- [ ] 真实 LLM 端到端(opt-in)可跑
- [ ] 8 对抗用例全绿(硬里程碑)
- [ ] web-src/ 前端构建后可对接(API 契约一致)

## 自检

**规格覆盖:** P0 三项全覆盖——HTTP 服务层(T1-T6)、真实 LLM(T8)、Web 对接(契约复刻 T3-T5,前端零改)。✅
**契约一致性:** event_to_agent_json 输出形状严格对齐 api.ts 的 AgentEvent(params_json/result_json/payload_json 是字符串,sanitize 是数组)。✅
**风险:** TestClient 的 WS 测试在 Windows 可能有时序敏感(补播 vs 实时);run_id 穿透改动触及 executor/pipeline,需确认现有测试不破。✅
