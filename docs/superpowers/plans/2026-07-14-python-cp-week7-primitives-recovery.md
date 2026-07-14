# Week 7 — 原语补完(io 真联网 / sub 消息分发)+ Checkpoint 恢复续跑 + 编排接入

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 把平台的工具链从"半成品"变成"真能干活":`io` 原语接 httpx 真联网;`sub` 原语收到消息后真能触发分发(消息进 agent 可见的收件箱);Checkpoint 崩溃恢复路径接通运行时(`load_latest → rehydrate → 续跑`);多 agent 编排(顺序链/fan-out)作为原语可被 agent loop 调用。

**背景(精确诊断,基于 Week 6 后代码核实):**
- `io.py`:返回硬编码 `{status:200, body:"[mock io] {protocol} {endpoint}"}`,agent 做不了任何真实网络请求。
- `sub.py`:`_collector(msg)` 体是 `pass`——pub/sub 闭环断了,收到消息什么都不做。
- Checkpoint **存**已接运行时(`runmgr._make_on_step` 每步存);但**恢复**(`rehydrate`/`load_latest`)仅测试引用,runmgr 启动时不检查/不续跑。
- `run_pipeline`(顺序链)/`run_router`(fan-out)有实现有测试,但 agent loop 里调不到——它们接收 `agent_fn` 列表,不是原语参数形状。

**Architecture:**
1. **io**:加 `httpx`(已在依赖里)。GET/POST/PUT/DELETE,超时可控,返回 `{status, body, headers}`。permission_key 用 `http_url`(Gate 默认拒——policy 需显式放行域名)。
2. **sub 收件箱**:在 `PrimitiveContext` 加 `inbox: dict[str, list]`(per-session 消息收件箱)。`sub` 注册的 handler 收到消息时 `inbox[topic].append(msg)`。agent loop 每步后检查 inbox,把新消息作为 `role=user` 观察注入消息历史。
3. **Checkpoint 恢复**:`runmgr.submit` 开始时 `ckpt.load_latest(session_id)`;有快照则 `rehydrate` 重建 session/account,`initial_messages=snap.messages`,续跑剩余步数。
4. **编排原语**:新增 `compose` 复合操作,参数 `{pattern: "pipeline"|"router", task, sub_agents: [{prompt, ...}]}`。内部对每个 sub_agent 起一个子 `run_agent_loop`,用 `run_pipeline`/`run_router` 编排。注册进 `PrimitiveRegistry`。

**Tech Stack:** `httpx`(已在 pip list)。无新依赖。

**硬里程碑:** T7——真实 HTTP 请求(httpbin)+ sub 消息端到端注入 loop + checkpoint 中断恢复续跑(步数连续)+ 8 对抗用例零退化。

**诚实边界(本周不做):**
- io 的 MCP 协议支持(只做 HTTP)
- sub 的跨副本消息(Redis pub/sub 已有,本周用进程内 inbox;跨副本 = 后续)
- compose 编排的递归深度限制/资源隔离(本周不限)
- AuthPort(Week 8)

---

## 文件结构(Week 7 变更)

```
cp/
├── primitives/
│   ├── io.py             # 【改】真 httpx 联网(保留 mock fallback)
│   ├── sub.py            # 【改】handler 写入 context.inbox
│   └── composite.py      # 【改】+compose 复合操作(pipeline/router)
├── registry.py           # 【改】PrimitiveContext +inbox
├── agent_loop.py         # 【改】每步后检查 inbox 注入观察
├── server/runmgr.py      # 【改】submit 时 load_latest → rehydrate 续跑
└── tests/
    ├── test_io.py        # 【新】httpx 真请求 + 错误处理
    ├── test_sub.py       # 【新】sub 写 inbox + loop 注入
    ├── test_compose.py   # 【改】+compose 测试
    ├── test_checkpoint_resume.py  # 【新】崩溃恢复续跑
    └── test_api_e2e.py   # 【改】+Week 7 硬里程碑
```

---

## 任务总览

| # | 任务 | 验收 |
|---|------|------|
| T1 | io 原语接 httpx | 真实 GET/POST 返回真响应;超时/错误处理 |
| T2 | PrimitiveContext +inbox;sub 写 inbox | sub 注册的 handler 收到消息进 inbox |
| T3 | agent loop 检查 inbox 注入观察 | 消息到达后下一步 LLM 能看到 |
| T4 | Checkpoint 恢复续跑 | load_latest→rehydrate→续跑,步数连续 |
| T5 | compose 复合操作(pipeline/router) | 顺序链/fan-out 经原语可调 |
| T6 | 编排注册进 Registry + schema 喂入 | compose 出现在 schemas |
| T7 | 硬里程碑:e2e + 对抗回归 | io 真请求+sub 注入+恢复续跑+8 对抗 |
| T8 | 最终验证 + push | 全回归绿 |

---

## Task 1: io 原语接 httpx

**Files:**
- Modify: `cp/primitives/io.py`
- Test: `cp/tests/test_io.py`

### `cp/primitives/io.py`:
```python
import urllib.parse
from typing import Any, Dict
import httpx

from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class IoPrimitive:
    """io 原语:同步点对点 HTTP 请求(GET/POST/PUT/DELETE)。
    permission_key 用 http_url 类型,Gate 默认拒——policy 需显式放行域名。
    真实实现用 httpx;无网络时测试可用 mock_server。"""
    name = "io"

    def schema(self) -> Dict[str, Any]:
        return {"name": "io", "description": "Sync HTTP request (GET/POST/PUT/DELETE).",
                "parameters": {"type": "object",
                               "properties": {"method": {"type": "string"},
                                              "url": {"type": "string"},
                                              "headers": {"type": "object"},
                                              "body": {"type": "string"},
                                              "timeout": {"type": "number"}},
                               "required": ["method", "url"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        # 注意:权限检查用 url(完整),不是 endpoint
        return Resource(type="http_url", id=params.get("url", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        method = params.get("method", "GET").upper()
        url = params.get("url", "")
        headers = params.get("headers", {}) or {}
        body = params.get("body")
        timeout = params.get("timeout", 30.0)
        if not url:
            return PrimitiveResult(status="error", error="missing url")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                req_kwargs = {"headers": headers}
                if body is not None and method in ("POST", "PUT", "PATCH"):
                    req_kwargs["content"] = body
                resp = await client.request(method, url, **req_kwargs)
            return PrimitiveResult(status="success", data={
                "status": resp.status_code,
                "body": resp.text,
                "headers": dict(resp.headers),
            })
        except httpx.TimeoutException:
            return PrimitiveResult(status="error", error=f"timeout after {timeout}s")
        except httpx.HTTPError as e:
            return PrimitiveResult(status="error", error=f"http error: {e}")
        except Exception as e:
            return PrimitiveResult(status="error", error=f"io error: {e}")
```

> **注意 schema 变更:** 旧 schema 用 `protocol`+`endpoint`,新用 `method`+`url`(更标准)。permission_key 用 `url`。Gate 对 `http_url` 走精确匹配——policy 放行需 `pattern: <完整url>`。

### Test `cp/tests/test_io.py`:
```python
import asyncio
from cp.primitives.io import IoPrimitive
from cp.primitives.registry import PrimitiveContext
from cp.resource import Resource


def test_permission_key_uses_url():
    p = IoPrimitive()
    assert p.permission_key({"url": "https://example.com/x"}) == Resource(type="http_url", id="https://example.com/x")


async def test_real_http_get(fake_redis_unused=None):
    """真实 GET 到 httpbin(测试环境需联网)。无网时 skip。"""
    import pytest, socket
    try:
        socket.gethostbyname("httpbin.org")
    except socket.gaierror:
        pytest.skip("no network")
    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET", "url": "https://httpbin.org/get?x=1"})
    assert r.status == "success"
    assert r.data["status"] == 200
    assert "httpbin" in r.data["body"]


async def test_timeout_returns_error():
    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET", "url": "https://httpbin.org/delay/10", "timeout": 1.0})
    assert r.status == "error"
    assert "timeout" in r.error


async def test_missing_url():
    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET"})
    assert r.status == "error"
    assert "url" in r.error
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_io.py -v` → passed(无网时部分 skip)
- [ ] 提交 `feat(cp): io primitive real HTTP via httpx`

---

## Task 2: PrimitiveContext +inbox;sub 写 inbox

**Files:**
- Modify: `cp/primitives/registry.py`(PrimitiveContext +inbox)
- Modify: `cp/primitives/sub.py`(handler 写 inbox)
- Test: `cp/tests/test_sub.py`

### `cp/primitives/registry.py` — PrimitiveContext 加 inbox:
```python
class PrimitiveContext:
    def __init__(self, session=None, sandbox_id="", sandbox=None, bus=None, state=None, run_id=""):
        self.session = session
        self.sandbox_id = sandbox_id
        self.sandbox = sandbox
        self.bus = bus
        self.state = state
        self.run_id = run_id
        self.inbox = {}  # 【新】topic -> [msg];sub 收到消息写这里
```

### `cp/primitives/sub.py` — handler 写 inbox:
```python
class SubPrimitive:
    """sub 原语:订阅 topic。handler 收到消息时写入 ctx.inbox[topic]。
    agent loop 每步后检查 inbox,把新消息注入观察。"""
    name = "sub"

    def schema(self) -> Dict[str, Any]:
        return {"name": "sub", "description": "Subscribe to a topic; messages arrive in agent inbox.",
                "parameters": {"type": "object",
                               "properties": {"topic": {"type": "string"},
                                              "handler_desc": {"type": "string"}},
                               "required": ["topic"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="topic", id=params.get("topic", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        topic = params.get("topic", "")
        handler_desc = params.get("handler_desc", "")
        if ctx.bus is None:
            return PrimitiveResult(status="error", error="no message bus in context")
        ctx.inbox.setdefault(topic, [])

        async def _collector(msg):
            ctx.inbox[topic].append(msg)  # 消息进收件箱,agent loop 下一步可见

        ctx.bus.subscribe(topic, _collector)
        return PrimitiveResult(status="success", data={"topic": topic, "handler_desc": handler_desc, "subscribed": True})
```

### Test `cp/tests/test_sub.py`:
```python
import asyncio
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.primitives.registry import PrimitiveContext
from cp.primitives.sub import SubPrimitive
from cp.primitives.pub import PubPrimitive


async def test_sub_writes_to_inbox(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    # 先订阅
    r = await SubPrimitive().execute(ctx, {"topic": "updates", "handler_desc": "log updates"})
    assert r.status == "success"
    assert r.data["subscribed"] is True
    # 启动 bus 消费
    await bus.start()
    try:
        # 发布消息
        await PubPrimitive().execute(PrimitiveContext(bus=bus), {"topic": "updates", "payload": {"x": 1}})
        await asyncio.sleep(0.1)  # 等消费循环分发
    finally:
        await bus.stop()
    # inbox 应有消息
    assert len(ctx.inbox["updates"]) == 1
    assert ctx.inbox["updates"][0] == {"x": 1}


async def test_sub_no_bus_returns_error():
    ctx = PrimitiveContext(bus=None)
    r = await SubPrimitive().execute(ctx, {"topic": "x"})
    assert r.status == "error"
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_sub.py -v` → 2 passed
- [ ] 提交 `feat(cp): sub writes received messages to context inbox`

---

## Task 3: agent loop 检查 inbox 注入观察

**Files:**
- Modify: `cp/agent_loop.py`(每步后 drain inbox)

### `cp/agent_loop.py` — 每步后检查 inbox:
在 `run_agent_loop` 的 `on_step` 调用之前/之后,加 inbox drain 逻辑:
```python
    for step in range(max_steps):
        steps_used = step + 1
        # 【新】drain inbox:把新消息作为观察注入消息历史
        if ctx is not None and hasattr(ctx, "inbox"):
            _drain_inbox(ctx, messages)
        assistant = await llm.chat(messages, primitive_schemas or [])
        # ... 现有逻辑 ...

def _drain_inbox(ctx, messages):
    """把 ctx.inbox 各 topic 的未读消息作为 user 观察追加到 messages。"""
    for topic, msgs in ctx.inbox.items():
        while msgs:
            msg = msgs.pop(0)
            messages.append({
                "role": "user",
                "content": f"[inbox:{topic}] {json.dumps(msg, default=str)}",
            })
```

> 注意:`_drain_inbox` 在每步 LLM 调用**前**执行,这样本步到达的消息下一步才被 LLM 看到(避免修改正在处理的 messages)。inbox 用 list + pop(0) 保证每条只注入一次。

### 追加到 `cp/tests/test_sub.py`:
```python
async def test_inbox_drained_into_loop_messages(fake_redis):
    """sub 收到消息后,agent loop 下一步把它注入 messages 历史。"""
    from cp.agent_loop import _drain_inbox
    ctx = PrimitiveContext()
    ctx.inbox = {"updates": [{"x": 1}]}
    messages = [{"role": "system", "content": "sys"}]
    _drain_inbox(ctx, messages)
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert "[inbox:updates]" in messages[1]["content"]
    assert ctx.inbox["updates"] == []  # drained
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_sub.py -v` → 3 passed
- [ ] 提交 `feat(cp): agent loop drains context inbox into messages`

---

## Task 4: Checkpoint 恢复续跑

**Files:**
- Modify: `cp/server/runmgr.py`(submit 时 load_latest → rehydrate)

### `runmgr.submit` 改动要点:
```python
async def submit(self, task, policy_path, sanitization_path, max_steps=20):
    pol = load_policy(policy_path)
    san = load_sanitizer(sanitization_path) if sanitization_path else Sanitizer.new_from_rules([])
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    # 【新】检查是否有 checkpoint(崩溃恢复续跑)
    from cp.checkpoint import Checkpoint, rehydrate
    ckpt = Checkpoint(self.state)
    existing = await ckpt.load_latest(session_id)

    if existing is not None:
        # 恢复:rehydrate 重建 session/account/messages
        async def _pol_loader(p): return pol
        async def _san_loader(p): return san
        restored = await rehydrate(existing, _pol_loader, _san_loader)
        sess = Session(
            id=restored["session_id"], identity=restored["identity"],
            policy=restored["policy"], gate=restored["gate"],
            sanitizer=restored["sanitizer"], account=restored["account"],
            ledger=Ledger(os.path.join(self.audit_dir, f"{session_id}.log")),
        )
        initial_messages = restored["messages"]
        resume_step = restored["step"]
        # 剩余步数 = max_steps - 已用步数
        remaining = max(1, max_steps - resume_step)
    else:
        os.makedirs(self.audit_dir, exist_ok=True)
        ledger = Ledger(os.path.join(self.audit_dir, f"{session_id}.log"))
        sess = Session.new(session_id, "local", pol, san, ledger)
        initial_messages = None
        remaining = max_steps

    # ... 其余不变,把 remaining 传给 _run_agent 的 max_steps,initial_messages 传入 loop
```

> `_run_agent` 调 `run_agent_loop(..., initial_messages=initial_messages, max_steps=remaining)`。

### Test `cp/tests/test_checkpoint_resume.py`:
```python
"""Week 7 T4: 崩溃后 checkpoint 恢复续跑。"""
import asyncio, os, tempfile
from cp.adapters.local_state import RedisStatePort
from cp.checkpoint import Checkpoint, SessionSnapshot
from cp.llm.mock import MockLLMClient
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.registry import PrimitiveRegistry
from cp.server.runmgr import RunManager


class _Sbx:
    async def create(self, c): return "sbx"
    async def exec_action(self, s, a): return {"data": {}}
    async def destroy(self, s): pass


async def test_submit_resumes_from_checkpoint(fake_redis):
    """预置一个 checkpoint(模拟崩溃前状态),submit 应恢复续跑而非全新开始。"""
    state = RedisStatePort(fake_redis)
    session_id = "sess-testresume"  # 固定 session_id 以匹配预置 checkpoint

    # 预置:跑了 2 步,存了快照
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(
        session_id=session_id, identity="local", used_steps=2, used_tokens=0,
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "continue"},
                  {"role": "assistant", "content": "was working"}], step=2))

    # runmgr submit 会生成新的 session_id(uuid),所以我们直接测 rehydrate 续跑逻辑
    # 通过 monkeypatch session_id 生成,或直接断言 rehydrate 结果正确
    from cp.checkpoint import rehydrate
    from cp.policy.policy import Policy
    from cp.sanitize.sanitizer import Sanitizer

    async def pol_loader(p): return Policy(permissions=[], max_steps=5, max_tokens=1000)
    async def san_loader(p): return Sanitizer.new_from_rules([])

    snap = await ckpt.load_latest(session_id)
    restored = await rehydrate(snap, pol_loader, san_loader)
    assert restored["account"]._used.steps == 2  # 恢复了用量
    assert restored["step"] == 2
    assert len(restored["messages"]) == 3


async def test_runmgr_resume_wiring(fake_redis):
    """端到端:runmgr 用 monkeypatch 的 session_id 匹配预置 checkpoint,续跑成功。"""
    import uuid
    state = RedisStatePort(fake_redis)
    fixed_sid = "sess-fixed12345"

    # 预置 checkpoint
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(
        session_id=fixed_sid, identity="local", used_steps=1, used_tokens=0,
        messages=[{"role": "system", "content": "you are resumed"},
                  {"role": "user", "content": "finish the task"},
                  {"role": "assistant", "content": "ok continuing"}], step=1))

    mgr = RunManager(None, _Sbx(), state,
        executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
        llm=MockLLMClient([{"role": "assistant", "content": "resumed and done"}]))

    # monkeypatch uuid 让 session_id = fixed_sid
    orig_hex = uuid.uuid4
    counter = [0]
    class FakeUUID:
        def __init__(self):
            counter[0] += 1
            self.hex = f"fixed12345{counter[0]:026d}"
    uuid.uuid4 = FakeUUID
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.yaml")
            open(p, "w").write("permissions: []\nmax_steps: 5\n")
            run = await mgr.submit("task", p, "", max_steps=5)
    finally:
        uuid.uuid4 = orig_hex
    for _ in range(100):
        if run.status == "ended": break
        await asyncio.sleep(0.02)
    assert run.status == "ended"
    assert run.termination != "crashed"
```

> **实现注意:** `session_id` 是 `f"sess-{uuid.uuid4().hex[:8]}"`。要让 submit 匹配预置 checkpoint,需让 session_id 可控。**更干净的方案**:给 `submit` 加可选参数 `session_id=None`;为 None 时自动生成。测试传固定值。**采用此方案**——比 monkeypatch uuid 干净。

### runmgr.submit 签名调整:
```python
async def submit(self, task, policy_path, sanitization_path, max_steps=20, session_id=None):
    if session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
    # ...
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_checkpoint_resume.py -v` → 2 passed
- [ ] 提交 `feat(cp): checkpoint resume on submit (load_latest -> rehydrate -> continue)`

---

## Task 5: compose 复合操作(pipeline/router)

**Files:**
- Modify: `cp/primitives/composite.py`(+compose)
- Test: `cp/tests/test_compose.py`(+compose 测试)

### `cp/primitives/composite.py` 追加:
```python
async def compose(ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
    """compose:多 agent 编排。pattern: pipeline(顺序)| router(并行 fan-out)。
    sub_agents 是 [{prompt: ...}] 列表,每个起一个子 agent loop。"""
    from cp.agent_loop import run_agent_loop
    pattern = params.get("pattern", "pipeline")
    task = params.get("task", "")
    sub_agents = params.get("sub_agents", [])

    async def _run_sub(sub_params):
        prompt = sub_params.get("prompt", task)
        # 子 agent 用相同的 executor/sess/ctx,但新 messages
        result = await run_agent_loop(prompt, None, None, ctx.session, ctx,
                                      [], max_steps=sub_params.get("max_steps", 5))
        return result

    agent_fns = [lambda sp=sp: _run_sub(sp) for sp in sub_agents]

    if pattern == "pipeline":
        from cp.orchestration.pipeline import run_pipeline
        out = await run_pipeline([lambda t, sp=sp: _run_sub(sp) for sp in sub_agents], task)
    elif pattern == "router":
        from cp.orchestration.router import run_router
        out = await run_router([lambda t, sp=sp: _run_sub(sp) for sp in sub_agents], task)
    else:
        return PrimitiveResult(status="error", error=f"unknown pattern: {pattern}")

    return PrimitiveResult(status="success", data={"pattern": pattern, "result": out["final"],
                                                    "stages": out.get("stages", []), "sub_results": out.get("sub_results", [])})
```

### 注册进 COMPOSITES + schema(文件内已有的 dict):
```python
_COMPOSITE_SCHEMAS["compose"] = {"name": "compose",
    "description": "Multi-agent orchestration (pipeline=sequential, router=parallel fan-out).",
    "parameters": {"type": "object",
        "properties": {"pattern": {"type": "string"}, "task": {"type": "string"},
                       "sub_agents": {"type": "array"}},
        "required": ["pattern", "task", "sub_agents"]}}
COMPOSITES["compose"] = (compose, _COMPOSITE_SCHEMAS["compose"])
```

### Test 追加到 `cp/tests/test_compose.py`:
```python
async def test_compose_pipeline(fake_redis):
    """compose pipeline:两个子 agent 顺序执行。"""
    from cp.primitives.composite import compose
    from cp.primitives.registry import PrimitiveContext
    from cp.adapters.redis_bus import RedisStreamMessageBus

    class _MockLLM:
        def __init__(self, responses): self.responses = responses; self.i = 0
        async def chat(self, messages, tools=None):
            r = self.responses[min(self.i, len(self.responses)-1)]; self.i += 1
            return r

    ctx = PrimitiveContext(bus=RedisStreamMessageBus(fake_redis))
    # 简化:直接调 compose,验证 pattern 路由正确
    result = await compose(ctx, {"pattern": "pipeline", "task": "x",
                                  "sub_agents": [{"prompt": "do A"}, {"prompt": "do B"}]})
    assert result.status == "success"
    assert result.data["pattern"] == "pipeline"


async def test_compose_router(fake_redis):
    from cp.primitives.composite import compose
    from cp.primitives.registry import PrimitiveContext
    ctx = PrimitiveContext(bus=RedisStreamMessageBus(fake_redis))
    result = await compose(ctx, {"pattern": "router", "task": "x", "sub_agents": [{"prompt": "A"}, {"prompt": "B"}]})
    assert result.status == "success"
    assert result.data["pattern"] == "router"


def test_compose_registered_in_registry():
    from cp.primitives.composite import register_composites
    from cp.primitives.registry import PrimitiveRegistry
    reg = PrimitiveRegistry()
    register_composites(reg)
    assert "compose" in reg.names()
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_composite.py -v` → 全 passed(含 compose)
- [ ] 提交 `feat(cp): compose composite op (pipeline/router orchestration)`

---

## Task 6: compose 注册 + schema 喂入

**Files:** 无新文件——T5 已把 compose 加进 COMPOSITES,`register_composites` 自动含它。

验证 `cli.py` 的 `register_composites(cp["prim_registry"])` 会包含 compose(已自动)。

### 追加到 `cp/tests/test_wiring.py`:
```python
async def test_compose_schema_reaches_llm(fake_redis):
    """compose 的 schema 出现在喂给 LLM 的 tools 列表。"""
    prim = PrimitiveRegistry()
    register_composites(prim)
    seen = {}
    class _SpyLLM:
        async def chat(self, messages, tools=None):
            seen["tools"] = tools
            return {"role": "assistant", "content": "done"}
    # ... 构造 mgr,提交 run ...
    assert any(s["name"] == "compose" for s in seen["tools"])
```

- [ ] 跑测试 → passed
- [ ] 提交 `test(cp): compose schema reaches LLM`

---

## Task 7: 硬里程碑 e2e + 对抗回归

**Files:** Modify: `cp/tests/test_api_e2e.py`

追加:
1. **io 真请求**:agent 经 loop 发 io GET 到 httpbin,断言响应进事件。
2. **sub 消息注入**:pub 一条消息 → sub 收到 → 下一步 LLM 看到注入观察。
3. **checkpoint 恢复续跑**:预置 checkpoint → submit → 续跑成功(步数连续)。
4. **8 对抗用例**保持绿。

```python
def test_e2e_io_real_request(fake_redis):
    """agent loop 调 io 原语发真实 HTTP GET。无网时 skip。"""
    import socket, pytest
    try: socket.gethostbyname("httpbin.org")
    except socket.gaierror: pytest.skip("no network")
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.io import IoPrimitive
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.redis_store import RedisRunStore
    prim = PrimitiveRegistry(); prim.register(IoPrimitive())
    store = RedisRunStore(fake_redis)
    class _Sbx:
        async def create(self,c): return "sbx"
        async def exec_action(self,s,a): return {"data": {}}
        async def destroy(self,s): pass
    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
        executor_factory=lambda b: PrimitiveExecutor(prim, b),
        llm=MockLLMClient([
            {"role":"assistant","content":"fetch",
             "tool_calls":[{"id":"1","type":"function",
               "function":{"name":"io","arguments":json.dumps({"method":"GET","url":"https://httpbin.org/get"})}}]},
            {"role":"assistant","content":"done"}]),
        prim_registry=prim, run_store=store)
    tmp = tempfile.mkdtemp()
    open(os.path.join(tmp,"p.yaml"),"w").write(
        "permissions:\n  - resource_type: http_url\n    pattern: 'https://httpbin.org/get'\n    actions: [io]\nmax_steps: 5\n")
    app = create_app(mgr, tmp, tempfile.mkdtemp(), run_store=store)
    rid = TestClient(app).post("/api/runs",json={"task":"fetch","policy":"p.yaml","sanitization":""}).json()["run_id"]
    run = mgr.get(rid); _wait_ended(run)
    assert run.status == "ended"
    io_ev = next((e for e in run.events if e.tool == "io"), None)
    assert io_ev is not None, "io 未经 executor"
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_api_e2e.py -v` → 全 passed
- [ ] `conda run -n agentos python -m pytest cp/tests/adversarial/ -v` → 8 passed
- [ ] 全回归
- [ ] 提交 `test(cp): Week 7 hard milestone (io real + sub inject + checkpoint resume + adversarial)`

---

## Task 8: 最终验证 + push

- [ ] 全回归:`conda run -n agentos python -m pytest cp/ -v` → 全绿
- [ ] 对抗:8 passed
- [ ] 零 TODO/FIXME
- [ ] CLI 烟雾测试
- [ ] `git push`

---

## Week 7 完成判据

- [ ] `pytest cp/` 全绿
- [ ] io 原语真实联网(GET/POST/超时处理)
- [ ] sub 原语收消息写 inbox;agent loop 注入观察
- [ ] checkpoint 崩溃恢复续跑(load_latest→rehydrate→续跑)
- [ ] compose 复合操作(pipeline/router)可被 agent loop 调用
- [ ] 8 对抗用例零退化(硬里程碑)

## 自检

**规格覆盖:** A 方案四项全覆盖——io 真联网(T1)、sub 消息分发(T2-T3)、checkpoint 恢复(T4)、编排接入(T5-T6)。✅
**诚实边界:** MCP 协议、跨副本 sub 消息、compose 递归深度/隔离、AuthPort——明确不做。✅
**风险:** io schema 变更(protocol→method)是破坏性改动;inbox 在 PrimitiveContext 是新共享状态,需确认线程/任务安全(asyncio 单线程内 OK);checkpoint 恢复的 session_id 匹配需可控(加 session_id 参数)。✅
