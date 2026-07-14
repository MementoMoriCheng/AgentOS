# Week 6 — 接线(孤儿模块接入运行时)+ 无状态化(Run 事件落 Redis)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 把已实现但未接入运行时的 V2 模块(4 复合操作、Checkpoint、Scheduler、HarnessRouter、原语 schema)接进 agent loop,让系统从"能 demo"变成"复合操作可达、可中断恢复、按任务路由、LLM 知道工具"。同时把 Run 事件/元数据从进程内存迁到 Redis,**让约束 6(控制面无状态)在可观测面上成立**——任一副本能 `GET /api/runs`、回放任意 run 的事件。

**背景(精确诊断):**
- 复合操作(`composite.py`)是裸 `async def`,不实现 Primitive Protocol → 无法注册。
- `runmgr` 传 `primitive_schemas=[]` → **LLM 不知道有哪些原语,工具层不可达**。
- **双总线接线错误**:`pub`/`sub`/复合操作调 `ctx.bus.publish(topic, payload)`(2 参,Redis Stream 风格);executor/pipeline 调 `bus.publish(Event(...))`(1 参,InProcess 风格)。当前 `runmgr` 把 `ctx.bus` 设成 InProcess → pub/sub 一调就崩(测试里它们用 RedisStreamMessageBus 才过的)。
- `Checkpoint`/`Scheduler`/`HarnessRouter` 有实现有测试,无调用方。

**Architecture:**
1. **双总线明确分离**:`audit_bus = InProcess()`(executor 的审计/可观测事件:`primitive.called`/`run.*`)与 `msg_bus = RedisStreamMessageBus(redis)`(ctx.bus,pub/sub/复合操作的 topic 消息)。runmgr 各自接线。
2. **CompositePrimitive 适配器**:把裸复合函数包成 Primitive Protocol,注册进 PrimitiveRegistry。`PrimitiveRegistry.schemas()` 暴露所有原语 schema。
3. **run_agent_loop 扩展**:加 `system_prompt`(HarnessRouter 选 profile)、`on_step(messages, step)` 回调(Checkpoint 每步存)、`initial_messages`(恢复续跑)。
4. **RedisRunStore**:Run 元数据(HSET)+ 事件(RPUSH list)+ 实时通道(PUBLISH/SUBSCRIBE)。WS 回放读 list、实时订阅 channel——**跨副本**。进程内只留正在执行的 run 句柄。

**Tech Stack:** 已有(fakeredis / redis.asyncio / pytest-asyncio)。无新依赖。

**硬里程碑:** T8——agent loop 真实调用一个复合操作(spawn_agent)+ 中断后 Checkpoint 恢复续跑 + run 事件经 RedisRunStore 可被独立读取 + 8 对抗用例零退化 + 全回归。

**诚实边界(本周不做):**
- Run *执行任务*仍留在创建它的副本上(跨副本工作队列/租约 = Week 7)。本周解决的是"可观测面无状态":任一副本能读 run 列表/详情/事件回放。
- `sub` 原语仍记录式(handler 触发分发留后续)。
- Kafka / Postgres 留后续周。

---

## 文件结构(Week 6 变更)

```
cp/
├── primitives/
│   ├── composite.py          # 【改】CompositePrimitive 适配器 + COMPOSITES 注册表
│   └── registry.py           # 【改】PrimitiveRegistry.schemas()
├── agent_loop.py             # 【改】+system_prompt / on_step / initial_messages
├── server/
│   ├── runmgr.py             # 【改】双总线 + schema 喂入 + Checkpoint + Scheduler + Harness + RedisRunStore
│   ├── redis_store.py        # 【新】RedisRunStore(meta + events + pub/sub channel)
│   └── app.py                # 【改】WS/list/get 读 RedisRunStore
│   └── cli.py                # 【改】注入 RedisRunStore + msg_bus + scheduler + harness_router
└── tests/
    ├── test_composite.py     # 【改】加 CompositePrimitive 注册 + schemas 测试
    ├── test_wiring.py        # 【新】复合操作经 agent loop 可达 + schema 喂入
    ├── test_checkpoint_wiring.py  # 【新】每步存 + 恢复续跑
    ├── test_redis_store.py   # 【新】RedisRunStore
    └── test_api_e2e.py       # 【改】追加跨副本可观测 + 复合操作 e2e(硬里程碑)
```

---

## 任务总览

| # | 任务 | 验收 |
|---|------|------|
| T1 | CompositePrimitive 适配器 + schemas() | 4 复合操作可注册;schemas() 返回全部 |
| T2 | 双总线 + schema 喂入(关键正确性修复) | agent loop 里 LLM 收到 schema;pub/sub 不崩 |
| T3 | Checkpoint 每步存 + 恢复续跑 | save→rehydrate→续跑;步数连续 |
| T4 | Scheduler 限流 gate | 并发超限阻塞;释放后放行 |
| T5 | HarnessRouter 选 system_prompt | code 任务→claude-style prompt;默认→generic |
| T6 | RedisRunStore(meta + events + channel) | 跨实例 list/get/回放一致 |
| T7 | WS + list/get 读 RedisRunStore | 跨副本回放 + 实时 |
| T8 | 硬里程碑 e2e + 对抗回归 | 复合操作经 loop + 恢复 + 跨副本 + 8 对抗 |
| T9 | 最终验证 + push | 全回归绿 |

---

## Task 1: CompositePrimitive 适配器 + PrimitiveRegistry.schemas()

**Files:**
- Modify: `cp/primitives/registry.py`(加 `schemas()`)
- Modify: `cp/primitives/composite.py`(加 `CompositePrimitive` + `COMPOSITES` 注册表)
- Modify: `cp/tests/test_composite.py`(追加注册/schemas 测试)

### `cp/primitives/registry.py` — 加公开 schemas 访问器:
```python
class PrimitiveRegistry:
    # ... 现有 __init__/register/get/names ...

    def schemas(self) -> List[Dict[str, Any]]:
        """所有已注册原语/复合操作的 LLM schema 列表(喂给 agent loop)。"""
        return [p.schema() for p in self._prims.values()]
```

### `cp/primitives/composite.py` — 追加适配器 + 注册表(文件末尾):
```python
from cp.resource import Resource

# 复合操作的 LLM schema(骨架固定,参数动态)
_COMPOSITE_SCHEMAS = {
    "spawn_agent": {"name": "spawn_agent",
        "description": "Fork a child agent (fixed skeleton: pub created -> child ReAct -> pub completed).",
        "parameters": {"type": "object",
            "properties": {"agent_type": {"type": "string"}, "prompt": {"type": "string"},
                           "context_mode": {"type": "string"}},
            "required": ["agent_type", "prompt"]}},
    "compress_context": {"name": "compress_context",
        "description": "Summarize and persist session context (llm summary -> write kv).",
        "parameters": {"type": "object",
            "properties": {"session_id": {"type": "string"}, "history": {"type": "array"},
                           "strategy": {"type": "string"}},
            "required": ["session_id", "history"]}},
    "generate_skill": {"name": "generate_skill",
        "description": "Generate a reusable skill file from session history.",
        "parameters": {"type": "object",
            "properties": {"skill_name": {"type": "string"}, "session_history": {"type": "string"}},
            "required": ["skill_name"]}},
    "handoff": {"name": "handoff",
        "description": "Hand off context to another agent (read kv context -> pub handoff).",
        "parameters": {"type": "object",
            "properties": {"from_agent": {"type": "string"}, "to_agent": {"type": "string"},
                           "session_id": {"type": "string"}},
            "required": ["to_agent"]}},
}


class CompositePrimitive:
    """适配器:把裸复合函数(async def f(ctx, params))包成 Primitive Protocol。
    permission_key 用专用 resource_type='composite',policy 可统一放行/收口。"""
    def __init__(self, name: str, func, schema: Dict[str, Any]):
        self.name = name
        self._func = func
        self._schema = schema

    def schema(self) -> Dict[str, Any]:
        return self._schema

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="composite", id=self.name)

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        return await self._func(ctx, params)


# 复合操作注册表:name -> (func, schema)
COMPOSITES = {
    "spawn_agent": (spawn_agent, _COMPOSITE_SCHEMAS["spawn_agent"]),
    "compress_context": (compress_context, _COMPOSITE_SCHEMAS["compress_context"]),
    "generate_skill": (generate_skill, _COMPOSITE_SCHEMAS["generate_skill"]),
    "handoff": (handoff, _COMPOSITE_SCHEMAS["handoff"]),
}


def register_composites(registry) -> None:
    """把 4 复合操作包成 CompositePrimitive 注册进 PrimitiveRegistry。"""
    for name, (func, schema) in COMPOSITES.items():
        registry.register(CompositePrimitive(name, func, schema))
```

### Test 追加到 `cp/tests/test_composite.py`:
```python
def test_composite_primitive_adapter_conforms_to_protocol():
    from cp.primitives.composite import CompositePrimitive, COMPOSITES
    from cp.resource import Resource
    func, schema = COMPOSITES["spawn_agent"]
    p = CompositePrimitive("spawn_agent", func, schema)
    assert p.name == "spawn_agent"
    assert p.schema()["name"] == "spawn_agent"
    assert p.permission_key({}) == Resource(type="composite", id="spawn_agent")


def test_register_composites_into_registry():
    from cp.primitives.composite import register_composites
    from cp.primitives.registry import PrimitiveRegistry
    reg = PrimitiveRegistry()
    register_composites(reg)
    names = set(reg.names())
    assert {"spawn_agent", "compress_context", "generate_skill", "handoff"}.issubset(names)
    schemas = reg.schemas()
    schema_names = {s["name"] for s in schemas}
    assert "spawn_agent" in schema_names
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_composite.py -v` → 全 passed
- [ ] 提交 `feat(cp): CompositePrimitive adapter + PrimitiveRegistry.schemas()`

---

## Task 2: 双总线接线 + schema 喂入(关键正确性修复)

**问题:** `runmgr` 把 `ctx.bus` 设成 InProcess(audit bus),但 pub/sub/复合操作调 `ctx.bus.publish(topic, payload)`(2 参 Redis 风格)→ 一调就崩。

**Files:**
- Modify: `cp/server/runmgr.py`(双总线 + schema 喂入)

### `runmgr.py` 改动要点:
```python
class RunManager:
    def __init__(self, registry, sandbox, state,
                 executor_factory=None, llm=None, audit_dir="./audit",
                 msg_bus=None,            # 【新】RedisStreamMessageBus(pub/sub/复合操作用)
                 prim_registry=None,      # 【新】用于 schemas() 喂给 LLM
                 scheduler=None,          # 【新】T4
                 harness_router=None,     # 【新】T5
                 run_store=None):         # 【新】T6
        ...
        self.msg_bus = msg_bus
        self.prim_registry = prim_registry
        self.scheduler = scheduler
        self.harness_router = harness_router
        self.run_store = run_store

    async def submit(self, task, policy_path, sanitization_path, max_steps=20):
        pol = load_policy(policy_path)
        san = load_sanitizer(sanitization_path) if sanitization_path else Sanitizer.new_from_rules([])
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        os.makedirs(self.audit_dir, exist_ok=True)
        ledger = Ledger(os.path.join(self.audit_dir, f"{session_id}.log"))
        sess = Session.new(session_id, "local", pol, san, ledger)

        audit_bus = InProcess()              # 审计/可观测事件(primitive.called/run.*)
        msg_bus = self.msg_bus               # topic 消息(pub/sub/复合操作)—— 可为 None
        sandbox_id = await self.sandbox.create({"workspace": "."})

        executor = self.executor_factory(audit_bus) if self.executor_factory else None
        ctx = PrimitiveContext(
            session=sess, sandbox_id=sandbox_id, sandbox=self.sandbox,
            bus=msg_bus,                     # 【关键】ctx.bus = 消息总线(2 参风格)
            state=self.state, run_id=run_id,
        )

        schemas = self.prim_registry.schemas() if self.prim_registry else []
        system_prompt = self._select_system_prompt(task)   # T5
        run = Run(run_id=run_id, session_id=session_id, task=task)

        async def _collector(e: Event):
            run.events.append(e)
            if self.run_store:
                await self.run_store.append_event(run_id, _event_to_storable(e))
            for q in list(run.subscribers):
                try: q.put_nowait(e)
                except asyncio.QueueFull: pass

        audit_bus.subscribe(_collector)
        async with self._mu:
            self._runs[run_id] = run
        if self.run_store:
            await self.run_store.save_meta(run_id, {"run_id": run_id, "session_id": session_id,
                "task": task, "status": "running", "started_at": run.started_at})

        await audit_bus.publish(Event(type="run.started", session_id=session_id, run_id=run_id,
                                      payload={"task": task, "max_steps": max_steps}))
        asyncio.create_task(self._run_agent(run, sess, ctx, executor, audit_bus,
                                            schemas, system_prompt, max_steps))
        return run

    async def _run_agent(self, run, sess, ctx, executor, audit_bus, schemas, system_prompt, max_steps):
        release = await self.scheduler.acquire() if self.scheduler else None
        try:
            result = await run_agent_loop(run.task, self.llm, executor, sess, ctx,
                                          primitive_schemas=schemas,
                                          system_prompt=system_prompt,
                                          on_step=self._make_on_step(run.session_id, sess),
                                          max_steps=max_steps)
            run.final_answer = result["final_answer"]
            run.termination = result["termination"]
        except Exception as e:
            run.termination = "crashed"
            run.final_answer = f"error: {e}"
        finally:
            if release: release()
            await audit_bus.publish(Event(type="run.ended", session_id=run.session_id,
                run_id=run.run_id,
                payload={"termination": run.termination, "final_answer": run.final_answer}))
            if self.run_store:
                await self.run_store.save_meta(run.run_id, {"run_id": run.run_id,
                    "session_id": run.session_id, "task": run.task, "status": "ended",
                    "started_at": run.started_at, "final_answer": run.final_answer,
                    "termination": run.termination})
            run.status = "ended"
```

> `run_agent_loop` 在 T3 加 `system_prompt`/`on_step`;`_select_system_prompt`/`_make_on_step` 分别在 T5/T3 实现。本任务先让 schema 喂入 + ctx.bus=msg_bus 生效,T3/T5 填空。

### Test `cp/tests/test_wiring.py`(本任务部分):
```python
import asyncio, json, os, tempfile
from cp.adapters.local_state import RedisStatePort
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.llm.mock import MockLLMClient
from cp.primitives.composite import register_composites
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.registry import PrimitiveRegistry
from cp.server.runmgr import RunManager


class _Sbx:
    async def create(self, c): return "sbx"
    async def exec_action(self, s, a): return {"data": {}}
    async def destroy(self, s): pass


async def test_llm_receives_primitive_schemas(fake_redis):
    prim = PrimitiveRegistry()
    register_composites(prim)
    seen = {}
    class _SpyLLM:
        async def chat(self, messages, tools=None):
            seen["tools"] = tools
            return {"role": "assistant", "content": "done"}
    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(prim, b), llm=_SpyLLM(),
                     msg_bus=RedisStreamMessageBus(fake_redis), prim_registry=prim)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        open(p, "w").write("permissions: []\nmax_steps: 3\n")
        run = await mgr.submit("t", p, "")
        for _ in range(100):
            if run.status == "ended": break
            await asyncio.sleep(0.02)
    assert seen["tools"], "schemas 未喂入 LLM"
    assert any(s["name"] == "spawn_agent" for s in seen["tools"])


async def test_pub_primitive_does_not_crash_with_redis_bus(fake_redis):
    """ctx.bus 是 RedisStreamMessageBus 时,pub 原语 publish(topic,payload) 不崩。"""
    from cp.primitives.pub import PubPrimitive
    from cp.primitives.registry import PrimitiveContext
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    r = await PubPrimitive().execute(ctx, {"topic": "t.x", "payload": {"a": 1}})
    assert r.status == "success"
    assert len(await fake_redis.xrange("t.x")) == 1
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_wiring.py -v` → 2 passed
- [ ] 全回归确认现有 runmgr 测试不破(可能需更新 _make 调用——runmgr 构造参数向后兼容,默认 None)
- [ ] 提交 `fix(cp): split audit bus vs message bus; feed primitive schemas to agent loop`

---

## Task 3: Checkpoint 每步存 + 恢复续跑

**Files:**
- Modify: `cp/agent_loop.py`(+ `system_prompt` / `on_step` / `initial_messages`)
- Modify: `cp/server/runmgr.py`(`_make_on_step`)
- Test: `cp/tests/test_checkpoint_wiring.py`

### `cp/agent_loop.py` — 扩展签名(全部向后兼容默认值):
```python
async def run_agent_loop(task, llm, executor, sess, ctx,
                         primitive_schemas=None, max_steps=20,
                         system_prompt=None, on_step=None, initial_messages=None):
    sys_msg = system_prompt or (
        "You are an autonomous agent. You have access to primitives (tools). "
        "Call a tool to accomplish the task. When done, respond with plain text.")
    messages = list(initial_messages) if initial_messages else [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""
    for step in range(max_steps):
        steps_used = step + 1
        assistant = await llm.chat(messages, primitive_schemas or [])
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            final_answer = assistant.get("content", "(no content)")
            if on_step: on_step(messages, steps_used)
            break
        for tc in tool_calls:
            # ... 现有执行逻辑不变 ...
        if on_step: on_step(messages, steps_used)   # 每步后存
    else:
        termination = "step_limit"
        final_answer = f"Reached step limit ({max_steps})."
        if on_step: on_step(messages, steps_used)
    return {"final_answer": final_answer, "steps_used": steps_used, "termination": termination}
```

### `runmgr.py` — `_make_on_step`:
```python
def _make_on_step(self, session_id, sess):
    from cp.checkpoint import Checkpoint, SessionSnapshot
    ckpt = Checkpoint(self.state)
    async def _on_step(messages, step):
        snap = SessionSnapshot(
            session_id=session_id,
            policy_path=getattr(sess.policy, "_path", ""),
            sanitization_path=getattr(sess.sanitizer, "_path", ""),
            identity=sess.identity,
            used_steps=sess.account._used.steps,
            used_tokens=sess.account._used.tokens,
            messages=messages, step=step,
        )
        await ckpt.save(snap)
    return _on_step
```
> 注:`on_step` 是同步回调(在 loop 内 await 之间调用);内部用 `asyncio.create_task(ckpt.save(...))` 或把 `_on_step` 改 async + loop 里 `await on_step(...)`。**采用 async**:`if on_step: await on_step(messages, steps_used)`。

### Test `cp/tests/test_checkpoint_wiring.py`:
```python
import asyncio, os, tempfile
from cp.adapters.local_state import RedisStatePort
from cp.audit.ledger import Ledger
from cp.checkpoint import Checkpoint, SessionSnapshot, rehydrate
from cp.llm.mock import MockLLMClient
from cp.policy.policy import Policy
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session
from cp.agent_loop import run_agent_loop


async def _policy_loader(p):
    return Policy(permissions=[], max_steps=5, max_tokens=1000)
async def _san_loader(p):
    return Sanitizer.new_from_rules([])


async def test_checkpoint_saved_each_step(fake_redis):
    state = RedisStatePort(fake_redis)
    ckpt = Checkpoint(state)
    saved = []
    async def on_step(messages, step):
        saved.append(step)
        await ckpt.save(SessionSnapshot(session_id="s1", used_steps=step, messages=messages, step=step))
    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local", Policy(permissions=[], max_steps=5, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        llm = MockLLMClient([
            {"role": "assistant", "content": "", "tool_calls": [{"id":"1","type":"function",
                "function":{"name":"read","arguments":"{}"}}]},
            {"role": "assistant", "content": "done"},
        ])
        # executor=None → tool 调用返回 [no executor]
        await run_agent_loop("t", llm, None, sess, None, [], max_steps=3, on_step=on_step)
    assert saved == [1, 2]   # 两步各存一次
    snap = await ckpt.load_latest("s1")
    assert snap is not None and snap.step == 2


async def test_rehydrate_resumes_usage(fake_redis):
    state = RedisStatePort(fake_redis)
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(session_id="s2", policy_path="", sanitization_path="",
                                    identity="local", used_steps=3, used_tokens=42,
                                    messages=[{"role":"system","content":"x"}], step=3))
    snap = await ckpt.load_latest("s2")
    restored = await rehydrate(snap, _policy_loader, _san_loader)
    assert restored["account"]._used.steps == 3
    assert restored["account"]._used.tokens == 42
    assert restored["messages"][0]["role"] == "system"
    assert restored["step"] == 3
```
> 注意:`Policy`/`Sanitizer` 无 `_path` 属性——on_step 里 `getattr(..., "_path", "")` 安全降级(空串)。`rehydrate` 的 loader 用闭包返回固定对象(测试不依赖文件)。

- [ ] `conda run -n agentos python -m pytest cp/tests/test_checkpoint_wiring.py -v` → 2 passed
- [ ] 提交 `feat(cp): checkpoint per-step + rehydrate resume`

---

## Task 4: Scheduler 限流 gate

已在 T2 的 `_run_agent` 里 `release = await self.scheduler.acquire() if self.scheduler else None` + finally `release()`。本任务只补测试。

### 追加到 `cp/tests/test_wiring.py`:
```python
async def test_scheduler_gates_concurrency(fake_redis):
    import asyncio
    from cp.scheduler.scheduler import Scheduler
    from cp.adapters.local_state import RedisStatePort
    from cp.llm.mock import MockLLMClient
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.runmgr import RunManager

    class _Sbx:
        async def create(self, c): return "sbx"
        async def exec_action(self, s, a): return {"data": {}}
        async def destroy(self, s): pass

    class _SlowLLM:
        def __init__(self): self.entered = 0; self.max_concurrent = 0
        async def chat(self, messages, tools=None):
            self.entered += 1
            self.max_concurrent = max(self.max_concurrent, self.entered)
            await asyncio.sleep(0.05)
            self.entered -= 1
            return {"role": "assistant", "content": "done"}

    slow = _SlowLLM()
    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
        executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b), llm=slow,
        scheduler=Scheduler(max_concurrent=1))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml"); open(p, "w").write("permissions: []\nmax_steps: 2\n")
        runs = [await mgr.submit("t", p, "") for _ in range(3)]
        for _ in range(200):
            if all(r.status == "ended" for r in runs): break
            await asyncio.sleep(0.02)
    assert slow.max_concurrent == 1   # 串行,并发槽=1
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_wiring.py::test_scheduler_gates_concurrency -v` → passed
- [ ] 提交 `feat(cp): wire Scheduler concurrency gate around run execution`

---

## Task 5: HarnessRouter 选 system_prompt

**Files:**
- Modify: `cp/server/runmgr.py`(`_select_system_prompt`)

```python
def _select_system_prompt(self, task: str) -> str:
    if not self.harness_router:
        return None  # agent_loop 用默认
    profile = self.harness_router.route(task)
    if profile and profile.system_prompt_template:
        return profile.system_prompt_template
    return None
```

### 追加到 `cp/tests/test_wiring.py`:
```python
async def test_harness_router_selects_prompt(fake_redis):
    from cp.harness.profile import HarnessProfile
    from cp.harness.router import HarnessRouter
    from cp.adapters.local_state import RedisStatePort
    from cp.llm.mock import MockLLMClient
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.runmgr import RunManager

    router = HarnessRouter()
    router.register(HarnessProfile(name="coder", system_prompt_template="YOU ARE A CODER",
                                   task_keywords=["code", "implement"]), is_default=False)
    router.register(HarnessProfile(name="generic", system_prompt_template="GENERIC"), is_default=True)

    seen_sys = {}
    class _Spy:
        async def chat(self, messages, tools=None):
            seen_sys["sys"] = next((m["content"] for m in messages if m["role"]=="system"), None)
            return {"role": "assistant", "content": "done"}

    mgr = RunManager(None, type("S",(),{"create":lambda s,c:"sbx","exec_action":lambda s,a,c:{"data":{}},
        "destroy":lambda s,c:None})() and __import__("asyncio").iscoroutine,
        type("S2",(),{"create":__import__("asyncio").coroutine(lambda s,c:"sbx"),
                      "exec_action":__import__("asyncio").coroutine(lambda s,a,c:{"data":{}}),
                      "destroy":__import__("asyncio").coroutine(lambda s,c:None)})(),
        RedisStatePort(fake_redis),
        executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b), llm=_Spy(),
        harness_router=router)
    # 注:上面的 inline sandbox 太丑——用一个简单 _Sbx 类(同上)
```
> **简化:** 用前面定义的 `_Sbx` 类,别写 inline 怪东西。测试断言:任务含 "implement" → `seen_sys["sys"] == "YOU ARE A CODER"`;纯任务 → "GENERIC"。

- [ ] `conda run -n agentos python -m pytest cp/tests/test_wiring.py::test_harness_router_selects_prompt -v` → passed
- [ ] 提交 `feat(cp): HarnessRouter selects agent system_prompt`

---

## Task 6: RedisRunStore(meta + events + pub/sub channel)

**Files:**
- Create: `cp/server/redis_store.py`
- Test: `cp/tests/test_redis_store.py`

### `cp/server/redis_store.py`:
```python
"""Run 状态的外部存储(Redis)。让约束 6(控制面无状态)在可观测面成立:
任一副本能 list/get/replay 任意 run;WS 实时经 pub/sub channel 跨副本。"""
import json
from typing import Any, Dict, List, Optional


class RedisRunStore:
    def __init__(self, redis):
        self._r = redis

    def _meta_key(self, run_id): return f"run:{run_id}:meta"
    def _events_key(self, run_id): return f"run:{run_id}:events"
    def _channel(self, run_id): return f"run:{run_id}:ch"

    async def save_meta(self, run_id: str, meta: Dict[str, Any]) -> None:
        await self._r.hset(self._meta_key(run_id), mapping={k: json.dumps(v, default=str) for k, v in meta.items()})

    async def get_meta(self, run_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._r.hgetall(self._meta_key(run_id))
        if not raw: return None
        return {k.decode() if isinstance(k, bytes) else k:
                json.loads(v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}

    async def append_event(self, run_id: str, event: Dict[str, Any]) -> None:
        await self._r.rpush(self._events_key(run_id), json.dumps(event, default=str))
        await self._r.publish(self._channel(run_id), json.dumps(event, default=str))

    async def get_events(self, run_id: str) -> List[Dict[str, Any]]:
        raw = await self._r.lrange(self._events_key(run_id), 0, -1)
        return [json.loads(x.decode() if isinstance(x, bytes) else x) for x in raw]

    async def list_runs(self) -> List[Dict[str, Any]]:
        # SCAN 所有 meta key(Week 6 量级足够;大规模可加索引)
        out = []
        async for k in self._r.scan_iter(match="run:*:meta"):
            key = k.decode() if isinstance(k, bytes) else k
            run_id = key.split(":")[1]
            meta = await self.get_meta(run_id)
            if meta: out.append(meta)
        return out

    def channel(self, run_id: str) -> str:
        return self._channel(run_id)
```

> `append_event` 接收的 event dict 由 runmgr 用 `event_to_agent_json(e)` 转换(复用 serialize.py)。

### Test `cp/tests/test_redis_store.py`:
```python
import json
from cp.server.redis_store import RedisRunStore


async def test_meta_roundtrip(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.save_meta("r1", {"run_id": "r1", "status": "running", "started_at": 1.5})
    m = await s.get_meta("r1")
    assert m["run_id"] == "r1"
    assert m["status"] == "running"
    assert m["started_at"] == 1.5
    assert await s.get_meta("missing") is None


async def test_events_append_and_list(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.append_event("r1", {"type": "run.started"})
    await s.append_event("r1", {"type": "primitive.called", "tool": "read"})
    evs = await s.get_events("r1")
    assert [e["type"] for e in evs] == ["run.started", "primitive.called"]


async def test_list_runs_scans_meta(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.save_meta("r1", {"run_id": "r1", "task": "a"})
    await s.save_meta("r2", {"run_id": "r2", "task": "b"})
    runs = await s.list_runs()
    ids = {r["run_id"] for r in runs}
    assert ids == {"r1", "r2"}


async def test_publish_to_channel(fake_redis):
    s = RedisRunStore(fake_redis)
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(s.channel("r1"))
    await s.append_event("r1", {"type": "run.ended"})
    msg = await pubsub.get_message(timeout=1.0)  # 可能先收到 subscribe 确认
    # 收到 subscribe 确认后下一个是真实消息
    while msg and msg.get("type") != "message":
        msg = await pubsub.get_message(timeout=1.0)
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "run.ended"
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_redis_store.py -v` → 4 passed
- [ ] 提交 `feat(cp): RedisRunStore (meta + events + pub/sub channel)`

---

## Task 7: WS + list/get 读 RedisRunStore

**Files:**
- Modify: `cp/server/app.py`(list/get/WS 用 run_store)

### `app.py` 改动:
- `create_app(mgr, ..., run_store=None)`。
- `GET /api/runs`(列表):若 `run_store` → `run_store.list_runs()`(跨副本);否则 `mgr.list_runs()`。
- `GET /api/runs?id=`:若 `run_store` → meta + events 从 store 读;否则进程内。
- `WS /api/events`:回放从 `run_store.get_events`;实时订阅 `run_store.channel`(`redis.pubsub()` + `get_message` 循环),收到 `run.ended` 关闭。无 store 时回退进程内 queue。

### 追加到 `cp/tests/test_api.py`:
```python
def test_cross_replica_run_visible_via_store(fake_redis):
    """副本 A 提交 run;副本 B(独立 RunManager,共享 redis)能读到 run + 事件。"""
    from cp.server.redis_store import RedisRunStore
    store = RedisRunStore(fake_redis)
    sandbox = LocalSandboxExecutor(Registry())
    mgrA = RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
        executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
        llm=MockLLMClient([{"role": "assistant", "content": "done"}]), run_store=store)
    pol = tempfile.mkdtemp(); open(os.path.join(pol,"p.yaml"),"w").write("permissions: []\nmax_steps: 3\n")
    appA = create_app(mgrA, pol, tempfile.mkdtemp(), run_store=store)
    rid = TestClient(appA).post("/api/runs", json={"task":"x","policy":"p.yaml","sanitization":""}).json()["run_id"]
    _wait_ended(mgrA.get(rid))
    # 副本 B:全新 mgrB(进程内无此 run),但共享 store
    mgrB = RunManager(Registry(), sandbox, RedisStatePort(fake_redis),
        executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
        llm=MockLLMClient([]), run_store=store)
    appB = create_app(mgrB, pol, tempfile.mkdtemp(), run_store=store)
    clientB = TestClient(appB)
    assert any(r["run_id"] == rid for r in clientB.get("/api/runs").json())
    detail = clientB.get(f"/api/runs?id={rid}").json()
    assert detail["run"]["run_id"] == rid
    assert any(e["type"] == "run.ended" for e in detail["events"])
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_api.py -v` → 全 passed
- [ ] 提交 `feat(cp): WS/list/get read from RedisRunStore (cross-replica observable)`

---

## Task 8: 硬里程碑 e2e + 对抗回归

**Files:**
- Modify: `cp/tests/test_api_e2e.py`

追加:
1. **复合操作经 agent loop 可达**:mock LLM 发 `spawn_agent` tool_call,policy 放行 `composite`,断言 `agent.*.created` 出现在 Redis Stream(msg_bus)。
2. **Checkpoint 恢复续跑**:跑 1 步 → 存 → rehydrate → 续跑,步数连续。
3. **跨副本可观测**:已在 T7 覆盖,这里复用断言。
4. **8 对抗用例**(已在文件内)保持绿。

```python
def test_e2e_composite_reachable_via_loop(fake_redis):
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.primitives.composite import register_composites
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.redis_store import RedisRunStore
    prim = PrimitiveRegistry(); register_composites(prim)
    store = RedisRunStore(fake_redis)
    mgr = RunManager(None, type("S",(),{
        "create": lambda s,c: __import__("asyncio").sleep(0,__import__("asyncio").iscoroutinefunction) or "sbx",
    })(), RedisStatePort(fake_redis),   # ← 用 _Sbx 类代替
        executor_factory=lambda b: PrimitiveExecutor(prim, b),
        llm=MockLLMClient([{"role":"assistant","content":"fork",
            "tool_calls":[{"id":"1","type":"function",
              "function":{"name":"spawn_agent","arguments":json.dumps({"agent_type":"researcher","prompt":"find x"})}}]},
            {"role":"assistant","content":"done"}]),
        msg_bus=RedisStreamMessageBus(fake_redis), prim_registry=prim, run_store=store)
    # policy 放行 composite
    tmp = tempfile.mkdtemp()
    open(os.path.join(tmp,"p.yaml"),"w").write(
        "permissions:\n  - resource_type: composite\n    pattern: '**'\n    actions: [execute]\nmax_steps: 5\n")
    app = create_app(mgr, tmp, tempfile.mkdtemp(), run_store=store)
    rid = TestClient(app).post("/api/runs", json={"task":"fork","policy":"p.yaml","sanitization":""}).json()["run_id"]
    _wait_ended(mgr.get(rid))
    # spawn_agent 内部 pub 到 msg_bus 的 Redis Stream
    created = await_or_sync(fake_redis.xrange("agent.researcher.created"))
    assert len(created) == 1
```
> **简化承诺:** 实现时用真实 `_Sbx` 类(不要 inline lambda 怪写法);`composite` resource_type 的 permission 需 Gate 支持——若 Gate 不认 `composite`,本测试改为断言 `primitive.called` 事件含 spawn_agent(证明经 executor 执行)而非依赖 msg_bus publish。**实现时先验证 Gate 对 composite 的行为,再定断言。**

- [ ] `conda run -n agentos python -m pytest cp/tests/test_api_e2e.py -v` → 全 passed
- [ ] `conda run -n agentos python -m pytest cp/tests/adversarial/ -v` → 8 passed(硬里程碑)
- [ ] 全回归 `conda run -n agentos python -m pytest cp/ -q`
- [ ] 提交 `test(cp): Week 6 hard milestone (composite via loop + checkpoint resume + cross-replica + adversarial)`

---

## Task 9: 最终验证 + push

- [ ] 全回归:`conda run -n agentos python -m pytest cp/ -v` → 全绿
- [ ] 对抗:8 passed
- [ ] 零 TODO/FIXME
- [ ] 验证 CLI:`conda run -n agentos python -m cp.server.cli serve`(smoke:POST/GET run)
- [ ] 更新 README(标注孤儿模块已接线 + 无状态化进展)
- [ ] `git push`

---

## Week 6 完成判据

- [ ] `pytest cp/` 全绿
- [ ] 4 复合操作经 PrimitiveRegistry + agent loop 可达
- [ ] LLM 收到原语 schema(工具层不再不可达)
- [ ] 每步 Checkpoint;rehydrate 恢复用量/消息/步数
- [ ] Scheduler 限流生效
- [ ] HarnessRouter 按 task_keywords 选 system_prompt
- [ ] Run 元数据/事件落 Redis;跨副本 list/get/replay 一致
- [ ] 8 对抗用例零退化(硬里程碑)

## 自检

**规格覆盖:** Tier 1 接线(复合操作/Checkpoint/Scheduler/Harness/schema)全覆盖;Tier 2 无状态化解决约束 6 在可观测面的违规(run-task 跨副本调度留 Week 7)。✅
**诚实边界:** 明确不做 run 执行任务的跨副本租约(Week 7)、sub 真实 handler 触发、Kafka/Postgres。这些在计划里标注,不在完成判据里。✅
**风险:** 双总线接线是行为变更(原 ctx.bus=InProcess 现=msg_bus);需确认现有 runmgr 测试不破(向后兼容:msg_bus=None 时退化为旧行为,但 pub/sub 会崩——只在 None 时)。Gate 对 `composite` resource_type 的支持需 T8 前验证。✅
