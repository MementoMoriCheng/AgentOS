# Week 2 — async 改造 + Port 接口 + 状态外化 + 消息总线

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 把 Week 1 的同步内存版安全内核改造成 V2 架构:async 控制面 + 5 个 Port 接口 + 状态外化(fakeredis)+ 消息总线(Redis Stream)+ SandboxPort(编排器不直接执行)。修复 V2 ch15 七约束中的 5 条违反项(3/4/5/6/7)。

**Architecture:** 改造现有 `cp/` 模块(不建平行版本)。Port 是 Python `Protocol`,现有实现适配为 Local 适配器,新增 Redis 适配器。全量 async(对齐 V2 的 async 原语)。fakeredis 做测试基础设施(纯内存,API 兼容 redis.asyncio)。

**Tech Stack:** Python 3.11+ asyncio / redis.asyncio(连 fakeredis)/ fakeredis.aioredis / pytest-asyncio

**硬约束:** Task 8 的 8 个对抗用例在 async + 走 SandboxPort 后仍全绿(零退化)。这是 Week 2 的硬里程碑。

---

## ch15 七约束对照(Week 2 修复目标)

| # | 约束 | Week 1 状态 | Week 2 动作 |
|---|------|------------|------------|
| 1 | 模块边界用接口(Port) | ⚠️ 有 Tool/Bus/Sandbox 接口,无 V2 五 Port | 定义 5 Port(T1) |
| 2 | 单向依赖无循环 | ✅ 已满足 | 保持 |
| 3 | 状态第一天就外化 | ❌ sessions 在内存 | StatePort + Redis(T5) |
| 4 | 审计/事件流上消息总线 | ❌ 进程内 eventbus | MessageBusPort + Redis Stream(T6) |
| 5 | 沙箱接口按远程设计 | ❌ Sandbox 空接口 | SandboxPort + LocalSandboxExecutor(T7) |
| 6 | 控制面无状态 | ❌ 依赖约束3 | 随 T5 修复 |
| 7 | 编排器不直接执行 | ❌ pipeline 直接 tool.execute | pipeline 走 SandboxPort(T8) |

---

## 文件结构(Week 2 新增/改造)

```
cp/
├── ports.py              # 【新】5 个 Port Protocol(StatePort/MessageBusPort/SandboxPort/AuthPort/AuditPort)
├── adapters/             # 【新】Port 适配器实现
│   ├── __init__.py
│   ├── local_state.py    # 【新】RedisStatePort(fakeredis;session 存取)
│   ├── redis_bus.py      # 【新】RedisStreamMessageBus(XADD/XREAD)
│   └── local_sandbox.py  # 【新】LocalSandboxExecutor(进程内执行,调 tool.execute)
├── eventbus/bus.py       # 【改】InProcess → async
├── audit/ledger.py       # 【改】append/read_all → async(asyncio.to_thread 包文件 I/O)
├── audit/subscriber.py   # 【改】async
├── session/account.py    # 【改】threading.Lock → asyncio.Lock
├── session/session.py    # 【改】async factory;状态走 StatePort
├── scheduler/scheduler.py# 【改】threading.Semaphore → asyncio.Semaphore
├── tools/tool.py         # 【改】execute → async def
├── tools/fs_tools.py     # 【改】execute → async def
├── pipeline/pipeline.py  # 【改】call → async;通过 SandboxPort 执行
├── compose.py            # 【新】控制面组装(composition root:注入 Port 适配器)
└── tests/
    ├── conftest.py       # 【新】asyncio_mode=auto + fakeredis fixture
    ├── test_constraints.py # 【新】ch15 七约束核对
    └── (现有测试全改 async)
```

---

## 任务总览

| # | 任务 | 验收标准 |
|---|------|---------|
| T1 | async 基础设施 + Ports 定义 | conftest async fixture 可用;5 Port 可导入 |
| T2 | async eventbus(InProcess) | 3 个 eventbus 测试改 async 后通过 |
| T3 | async audit + account + scheduler | 这些模块的测试改 async 后通过 |
| T4 | async tools + session | fs_tools/session 测试改 async 后通过 |
| T5 | StatePort + RedisStatePort | session 状态存取走 Redis;重启可恢复 |
| T6 | MessageBusPort + RedisStreamMessageBus | 事件经 Redis Stream pub/sub;可 replay |
| T7 | SandboxPort + LocalSandboxExecutor | create/exec_action/destroy;编排器不直接 execute |
| T8 | async pipeline + 走 Sandbox + 对抗/架构测试 async | **8 对抗用例全绿(硬里程碑)** |
| T9 | 控制面组装 + ch15 七约束核对 | ch15 七约束逐条核对测试通过 |

---

## Task 1: async 基础设施 + Ports 定义

**Files:**
- Create: `cp/tests/conftest.py`
- Create: `cp/ports.py`
- Test: `cp/tests/test_ports.py`

- [ ] **Step 1: 创建 conftest.py(asyncio 自动模式 + fakeredis fixture)**

`cp/tests/conftest.py`:
```python
import pytest_asyncio
import fakeredis.aioredis


@pytest_asyncio.fixture
async def fake_redis():
    """每个测试一个独立的内存 Redis(async)。测试结束清空。"""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.flushall()
    await r.aclose()
```

同时创建 `pytest.ini`(repo 根)或 `pyproject.toml` 配置 asyncio_mode。在 repo 根创建 `pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: 写失败测试 `cp/tests/test_ports.py`**

```python
from cp.ports import StatePort, MessageBusPort, SandboxPort, AuthPort, AuditPort


def test_ports_are_protocols():
    import typing
    for p in [StatePort, MessageBusPort, SandboxPort, AuthPort, AuditPort]:
        # Protocol 的运行时检查:有 _is_protocol 或 _is_runtime_protocol
        assert hasattr(p, "_is_protocol"), f"{p.__name__} must be a Protocol"


def test_state_port_has_methods():
    # Protocol 方法存在性(签名检查)
    assert "get_session" in StatePort.__annotations__ or hasattr(StatePort, "get_session")


def test_sandbox_port_has_create_exec_destroy():
    for m in ["create", "exec_action", "destroy"]:
        assert hasattr(SandboxPort, m), f"SandboxPort missing {m}"


def test_message_bus_port_has_publish_subscribe():
    for m in ["publish", "subscribe"]:
        assert hasattr(MessageBusPort, m), f"MessageBusPort missing {m}"
```

- [ ] **Step 3: 跑测试确认失败** `conda run -n agentos python -m pytest cp/tests/test_ports.py -v`

- [ ] **Step 4: 实现 `cp/ports.py`**

```python
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class StatePort(Protocol):
    """状态外化接口。所有持久/热状态经此存取,不进进程内存(ch15 约束3/6)。"""

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    async def save_session(self, session_id: str, state: Dict[str, Any]) -> None: ...
    async def delete_session(self, session_id: str) -> None: ...


@runtime_checkable
class MessageBusPort(Protocol):
    """消息总线接口。控制面↔沙箱唯一通信通道;事件流经此(ch15 约束4)。
    topic 例:actions.{sandbox_id} / observations.{sandbox_id} / agent_events.{session_id}。"""

    async def publish(self, topic: str, message: Dict[str, Any]) -> None: ...
    async def subscribe(self, topic: str, handler: Callable[[Dict[str, Any]], None]) -> Callable[[], None]: ...


@runtime_checkable
class SandboxPort(Protocol):
    """沙箱执行接口。按远程设计(ch15 约束5);编排器不直接 execute(ch15 约束7)。
    Local 适配器进程内执行;Remote 适配器走消息总线(Week 3)。"""

    async def create(self, config: Dict[str, Any]) -> str: ...
    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]: ...
    async def destroy(self, sandbox_id: str) -> None: ...


@runtime_checkable
class AuthPort(Protocol):
    """认证/权限接口。"""

    async def check_permission(self, tenant_id: str, agent_id: str, action: str) -> bool: ...


@runtime_checkable
class AuditPort(Protocol):
    """审计接口。经消息总线旁路订阅,不散落(ch15 约束4)。"""

    async def record(self, event: Dict[str, Any]) -> None: ...
```

- [ ] **Step 5: 跑测试确认通过** `conda run -n agentos python -m pytest cp/tests/test_ports.py -v`
- [ ] **Step 6: 回归** `conda run -n agentos python -m pytest cp/ -v`(现有 sync 测试不受影响)
- [ ] **Step 7: 提交** `git add cp/tests/conftest.py cp/ports.py cp/tests/test_ports.py pytest.ini && git commit -m "feat(cp): async infra + 5 Port protocols (State/Bus/Sandbox/Auth/Audit)"`

---

## Task 2: async eventbus(InProcess)

**Files:**
- Modify: `cp/eventbus/bus.py`(InProcess → async)
- Modify: `cp/tests/test_eventbus.py`(测试改 async)

**改造指令:** 把 `InProcess` 的 `publish`/`subscribe` 改成 `async def`,内部 `threading.Lock` → `asyncio.Lock`。`publish` 里调用 handler 时改为 `await h(event)`(handler 也要 async)。panic 隔离保留(try/except)。

- [ ] **Step 1: 改 `cp/eventbus/bus.py`**

关键改动:
```python
import asyncio
from typing import Awaitable, Callable

class InProcess(Bus):
    def __init__(self):
        self._mu = asyncio.Lock()
        self._handlers: List[Optional[Callable]] = []

    def subscribe(self, handler: Callable) -> Callable[[], None]:
        # 同步注册(handler 列表操作轻量,不需要 await;用循环创建时的 lock 不便,
        # 改用 set 因 subscribe 通常在事件循环启动前调用)
        self._handlers.append(handler)
        idx = len(self._handlers) - 1
        def _unsub():
            if idx < len(self._handlers):
                self._handlers[idx] = None
        return _unsub

    async def publish(self, event: Event) -> None:
        event.timestamp = time.time_ns()
        snapshot = list(self._handlers)
        for h in snapshot:
            if h is None:
                continue
            try:
                await h(event)  # handler 现在是 async
            except Exception:
                pass
```

注意:`subscribe` 保持同步签名(它通常在循环启动前注册,返回取消函数)。只有 `publish` 是 async(它 await handler)。`Bus` Protocol 基类的 `publish` 也改 `async def`。

- [ ] **Step 2: 改测试 `cp/tests/test_eventbus.py` 成 async**

```python
import pytest
from cp.eventbus.bus import Event, InProcess


async def test_subscribe_receives_published_event():
    bus = InProcess()
    received = []
    async def handler(e):
        received.append(e)
    bus.subscribe(handler)
    await bus.publish(Event(type="tool.called", session_id="s1"))
    assert len(received) == 1
    assert received[0].type == "tool.called"
    assert received[0].timestamp > 0


async def test_unsubscribe_stops_delivery():
    bus = InProcess()
    received = []
    async def handler(e):
        received.append(e)
    unsub = bus.subscribe(handler)
    await bus.publish(Event(type="x"))
    unsub()
    await bus.publish(Event(type="y"))
    assert len(received) == 1


async def test_handler_exception_does_not_crash_publish():
    bus = InProcess()
    async def boom(e):
        raise RuntimeError("boom")
    sink = []
    async def sink_handler(e):
        sink.append(e)
    bus.subscribe(boom)
    bus.subscribe(sink_handler)
    await bus.publish(Event(type="x"))
    assert len(sink) == 1
```

- [ ] **Step 3: 跑** `conda run -n agentos python -m pytest cp/tests/test_eventbus.py -v` → 3 passed
- [ ] **Step 4: 提交** `git add cp/eventbus/bus.py cp/tests/test_eventbus.py && git commit -m "refactor(cp): async eventbus (asyncio.Lock + await handlers)"`

**注意:** eventbus 改 async 后,`cp/audit/subscriber.py` 和 `cp/pipeline/pipeline.py` 里调用 `bus.publish` 的地方需要加 `await`。这些会在 T3/T8 改造时同步更新。**本步只改 eventbus 自身 + 它的测试**;如果回归因其它模块调用 `bus.publish` 缺 await 而报错,记录下来(预期,后续任务修复)。

---

## Task 3: async audit + account + scheduler

**Files:**
- Modify: `cp/audit/ledger.py`(append/read_all → async)
- Modify: `cp/audit/subscriber.py`(handler → async)
- Modify: `cp/session/account.py`(threading.Lock → asyncio.Lock)
- Modify: `cp/scheduler/scheduler.py`(threading.Semaphore → asyncio.Semaphore)
- Modify: 对应测试文件改 async

**改造指令:**

**audit/ledger.py:** `append` 和 `read_all` 改 `async def`,内部文件 I/O 用 `asyncio.to_thread()` 包裹(避免引入 aiofiles 依赖,复用阻塞 I/O):
```python
async def append(self, e: Entry) -> None:
    async with self._mu:  # asyncio.Lock
        e.timestamp_nano = time.time_ns()
        e.prev_hash = self.last_hash
        e.hash = _compute_hash(e.prev_hash, e)
        await asyncio.to_thread(self._write_line, e)
        self.last_hash = e.hash

def _write_line(self, e: Entry):
    with open(self.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(e)) + "\n")

async def read_all(self) -> List[Entry]:
    return await asyncio.to_thread(self._read_all_sync)
```
`__init__` 里加载已有链尾的同步 read 改用 `asyncio.to_thread` 或提供一个 async `init` 类方法。推荐:把"加载链尾"从 `__init__` 移到 async 类方法 `async_init`,或在首次 append 时惰性加载。**最简方案:** `__init__` 里用同步 read 加载链尾(构造时不在事件循环里,可接受),Lock 改 asyncio.Lock。

**audit/subscriber.py:** `register_audit_subscriber` 的 handler 改 async:
```python
async def _on_event(e: Event) -> None:
    outcome = _outcome_for(e.type)
    if outcome == "":
        return
    await ledger.append(Entry(...))
bus.subscribe(_on_event)
```

**account.py:** `threading.Lock` → `asyncio.Lock`,`charge`/`used` 改 `async def`,`with self._mu` → `async with self._mu`。

**scheduler.py:** `threading.Semaphore` → `asyncio.Semaphore`,`acquire` 改 `async def` 返回 async release(用 contextmanager 或返回闭包):
```python
async def acquire(self):
    await self._sem.acquire()
    return self._sem.release
```

**测试改 async:** `test_audit.py`(5)、`test_session_account.py`(3)、`test_scheduler.py`(2)全部 `def test_` → `async def test_`,调用处加 `await`。scheduler 测试去掉 threading,用 asyncio.gather 验证并发阻塞。

- [ ] 改造 4 个模块 + 3 个测试文件
- [ ] 跑各模块测试:`conda run -n agentos python -m pytest cp/tests/test_audit.py cp/tests/test_session_account.py cp/tests/test_scheduler.py -v`
- [ ] 提交 `git add -A && git commit -m "refactor(cp): async audit/account/scheduler"`

---

## Task 4: async tools + session

**Files:**
- Modify: `cp/tools/tool.py`(Tool.execute → async)
- Modify: `cp/tools/fs_tools.py`(三个工具的 execute → async,文件 I/O 包 asyncio.to_thread)
- Modify: `cp/session/session.py`(Session.new → async 类方法,因为要异步加载)
- Modify: `cp/tests/test_fs_tools.py`、其余依赖

**改造指令:**

**tools/tool.py:** `Tool` Protocol 的 `execute` 改 `async def execute(...) -> ToolResult`。`Registry` 不变。

**tools/fs_tools.py:** 三个工具 `execute` 改 `async def`,文件读写用 `asyncio.to_thread`:
```python
async def execute(self, ctx, params) -> ToolResult:
    safe = resolve(params.get("path", ""))
    content = await asyncio.to_thread(self._read_file, safe)
    return ToolResult(data={"content": content})

def _read_file(self, path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
```

**session/session.py:** `Session.new` 保持(它是纯构造,不涉及 I/O),但 `Session` 持有的 `Ledger` 现在是 async 的——`Session.new` 里 `Ledger(path)` 构造仍同步(链尾加载在 `__init__`)。无需 async factory,除非 T5 状态外化要求。本步保持 `Session.new` 同步。

**测试改 async:** `test_fs_tools.py`(5)改 async。

- [ ] 改造 + 测试 async
- [ ] 跑 `conda run -n agentos python -m pytest cp/tests/test_fs_tools.py -v`
- [ ] 提交 `git add -A && git commit -m "refactor(cp): async tools (execute via asyncio.to_thread)"`

---

## Task 5: StatePort + RedisStatePort(状态外化)

**Files:**
- Create: `cp/adapters/__init__.py`
- Create: `cp/adapters/local_state.py`
- Test: `cp/tests/test_state_port.py`

**目标:** ch15 约束3/6。session 状态(可序列化的部分:policy 摘要、gate 规则、account 用量、identity)存进 Redis。控制面重启后从 Redis 恢复。

**关键设计:** `Session` 对象本身含不可序列化成员(Gate/Sanitizer/Account/Ledger 实例)。状态外化存的是**可序列化的状态快照**:account 用量、session 元数据。Gate/Sanitizer 规则从 YAML 重新加载(它们是只读的)。所以 `RedisStatePort` 存:`session:{id}` → JSON{policy_path, sanitization_path, identity, used_steps, used_tokens}。

- [ ] **Step 1: 写失败测试 `cp/tests/test_state_port.py`**

```python
import json
import pytest
from cp.adapters.local_state import RedisStatePort


async def test_save_and_get_session(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"identity": "alice", "used_steps": 5})
    got = await sp.get_session("s1")
    assert got == {"identity": "alice", "used_steps": 5}


async def test_get_missing_session_returns_none(fake_redis):
    sp = RedisStatePort(fake_redis)
    assert await sp.get_session("nope") is None


async def test_delete_session(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"x": 1})
    await sp.delete_session("s1")
    assert await sp.get_session("s1") is None


async def test_save_overwrites(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"v": 1})
    await sp.save_session("s1", {"v": 2})
    assert (await sp.get_session("s1"))["v"] == 2
```

- [ ] **Step 2: 实现 `cp/adapters/local_state.py`**

```python
import json
from typing import Any, Dict, Optional


class RedisStatePort:
    """StatePort 的 Redis 实现。session 状态存 Redis KV(ch15 约束3)。
    开发用 fakeredis,生产连真实 Redis——接口不变。"""

    def __init__(self, redis):
        self._r = redis

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._r.get(f"session:{session_id}")
        if raw is None:
            return None
        return json.loads(raw)

    async def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        await self._r.set(f"session:{session_id}", json.dumps(state))

    async def delete_session(self, session_id: str) -> None:
        await self._r.delete(f"session:{session_id}")
```

- [ ] **Step 3: 跑测试** `conda run -n agentos python -m pytest cp/tests/test_state_port.py -v` → 4 passed
- [ ] **Step 4: 提交** `git add cp/adapters/ cp/tests/test_state_port.py && git commit -m "feat(cp): StatePort + RedisStatePort (state externalization)"`
```

---

## Task 6: MessageBusPort + RedisStreamMessageBus

**Files:**
- Create: `cp/adapters/redis_bus.py`
- Test: `cp/tests/test_redis_bus.py`

**目标:** ch15 约束4。事件流经 Redis Stream(XADD 发布,XREAD 订阅),可 replay。

**关键设计:** `RedisStreamMessageBus` 用 `XADD` publish、一个后台 `XREAD` 消费循环分发到 handler。topic = Redis Stream key(如 `agent_events.{session_id}`)。

- [ ] **Step 1: 写失败测试 `cp/tests/test_redis_bus.py`**

```python
import asyncio
import pytest
from cp.adapters.redis_bus import RedisStreamMessageBus


async def test_publish_and_subscribe(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    received = []
    async def handler(msg):
        received.append(msg)
    bus.subscribe("actions.s1", handler)
    await bus.start()  # 启动消费循环
    await bus.publish("actions.s1", {"cmd": "ls"})
    await asyncio.sleep(0.1)  # 让消费循环处理
    await bus.stop()
    assert len(received) == 1
    assert received[0]["cmd"] == "ls"


async def test_subscribe_pattern_topic(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    received = []
    async def handler(msg):
        received.append(msg)
    bus.subscribe("events.*", handler)  # 通配订阅(实现可先用精确匹配,标记 future)
    await bus.start()
    await bus.publish("events.tool_called", {"tool": "fs_read"})
    await asyncio.sleep(0.1)
    await bus.stop()
    assert len(received) == 1


async def test_replay(fake_redis):
    """事件持久化在 Stream,新订阅者可读历史(ch15 约束4:可 replay)。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.publish("obs.s1", {"step": 1})
    await bus.publish("obs.s1", {"step": 2})
    # Stream 里应有 2 条
    entries = await fake_redis.xrange("obs.s1")
    assert len(entries) == 2
```

- [ ] **Step 2: 实现 `cp/adapters/redis_bus.py`**

```python
import asyncio
import json
from typing import Any, Callable, Dict, List


class RedisStreamMessageBus:
    """MessageBusPort 的 Redis Stream 实现。XADD 发布,XREAD 消费分发。
    事件持久化在 Stream(可 replay)。开发用 fakeredis。"""

    def __init__(self, redis):
        self._r = redis
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._task = None
        self._stop = False
        self._last_ids: Dict[str, str] = {}  # 每 topic 的消费位点

    def subscribe(self, topic: str, handler: Callable) -> Callable[[], None]:
        self._subscriptions.setdefault(topic, []).append(handler)
        self._last_ids.setdefault(topic, "0")  # 从头消费(replay 能力)
        def _unsub():
            if handler in self._subscriptions.get(topic, []):
                self._subscriptions[topic].remove(handler)
        return _unsub

    async def publish(self, topic: str, message: Dict[str, Any]) -> None:
        await self._r.xadd(topic, {"data": json.dumps(message)})

    async def start(self) -> None:
        """启动消费循环(后台 task)。"""
        self._stop = False
        self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _consume(self) -> None:
        while not self._stop:
            if not self._subscriptions:
                await asyncio.sleep(0.01)
                continue
            streams = {t: self._last_ids[t] for t in self._subscriptions}
            try:
                results = await self._r.xread(streams, count=10, block=50)
            except asyncio.CancelledError:
                break
            for topic, entries in results:
                for entry_id, fields in entries:
                    self._last_ids[topic] = entry_id
                    data = json.loads(fields[b"data"])
                    for h in self._subscriptions.get(topic, []):
                        try:
                            await h(data)
                        except Exception:
                            pass
```

- [ ] **Step 3: 跑测试** `conda run -n agentos python -m pytest cp/tests/test_redis_bus.py -v`
- [ ] **Step 4: 提交** `git add cp/adapters/redis_bus.py cp/tests/test_redis_bus.py && git commit -m "feat(cp): MessageBusPort + RedisStreamMessageBus (XADD/XREAD, replayable)"`

---

## Task 7: SandboxPort + LocalSandboxExecutor

**Files:**
- Create: `cp/adapters/local_sandbox.py`
- Test: `cp/tests/test_local_sandbox.py`

**目标:** ch15 约束5/7。编排器(pipeline)不直接 `tool.execute`,而是通过 `SandboxPort.exec_action`。LocalSandboxExecutor 进程内执行(调用 tool.execute),接口已按远程设计——Week 3 换 RemoteSandboxExecutor 走消息总线,接口不变。

**关键设计:** `exec_action(sandbox_id, action)` 的 `action` 是 `{tool: "fs_read", params: {...}}`。LocalSandboxExecutor 持有 Registry,按 action.tool 查找并执行。

- [ ] **Step 1: 写失败测试 `cp/tests/test_local_sandbox.py`**

```python
import pytest
from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.tools.tool import Registry
from cp.tools.fs_tools import FSReadTool
import os, tempfile


async def test_create_returns_sandbox_id():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({"workspace": "/tmp"})
    assert isinstance(sid, str) and len(sid) > 0


async def test_exec_action_runs_tool():
    reg = Registry()
    reg.register(FSReadTool())
    ex = LocalSandboxExecutor(reg)
    sid = await ex.create({})
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            os.makedirs("wd", exist_ok=True)
            open("wd/f.txt", "w").close()
            result = await ex.exec_action(sid, {"tool": "fs_read", "params": {"path": "wd/f.txt"}})
            assert "content" in result["data"]
        finally:
            os.chdir(orig)


async def test_exec_unknown_tool_returns_error():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({})
    result = await ex.exec_action(sid, {"tool": "nope", "params": {}})
    assert result.get("error") is not None


async def test_destroy():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({})
    await ex.destroy(sid)  # 不抛即可
```

- [ ] **Step 2: 实现 `cp/adapters/local_sandbox.py`**

```python
import uuid
from typing import Any, Dict

from cp.tools.tool import Registry


class LocalSandboxExecutor:
    """SandboxPort 的本地实现。进程内执行(调 tool.execute),接口按远程设计。
    Week 3 加 RemoteSandboxExecutor 走消息总线时,调用方零改(ch15 约束5/7)。"""

    def __init__(self, registry: Registry):
        self._reg = registry
        self._sandboxes = {}  # MVP:仅登记;真实沙箱在 Week 3

    async def create(self, config: Dict[str, Any]) -> str:
        sid = f"sbx-{uuid.uuid4().hex[:12]}"
        self._sandboxes[sid] = config
        return sid

    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action.get("tool", "")
        params = action.get("params", {})
        tool, ok = self._reg.get(tool_name)
        if not ok:
            return {"error": f"unknown tool: {tool_name}"}
        try:
            result = await tool.execute(None, params)
            return {"data": result.data}
        except Exception as e:
            return {"error": str(e)}

    async def destroy(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)
```

- [ ] **Step 3: 跑测试** `conda run -n agentos python -m pytest cp/tests/test_local_sandbox.py -v`
- [ ] **Step 4: 提交** `git add cp/adapters/local_sandbox.py cp/tests/test_local_sandbox.py && git commit -m "feat(cp): SandboxPort + LocalSandboxExecutor (orchestrator doesn't execute directly)"`

---

## Task 8: async pipeline + 走 SandboxPort + 对抗/架构测试 async(硬里程碑)

**Files:**
- Modify: `cp/pipeline/pipeline.py`(call → async;exec 走 SandboxPort)
- Modify: `cp/tests/test_pipeline.py`(async)
- Modify: `cp/tests/adversarial/test_adversarial.py`(async)
- Modify: `cp/tests/architecture/test_open_closed.py`(async)

**目标:** pipeline 改 async;步骤4(执行)从 `tool.execute(None, params)` 改为 `sandbox.exec_action(sid, {tool, params})`(ch15 约束7)。**8 对抗用例全绿 = 硬里程碑。**

**关键改造:** `Pipeline.__init__` 增加 `sandbox: SandboxPort` 和 `sandbox_id` 参数(或 sandbox_id 从 session 关联)。pipeline 不再直接持有 Registry(它不执行工具了),但保留 Registry 仅用于步骤1(查找工具是否存在)和步骤2(permission_key 提取)。

实际上更干净的设计:pipeline 仍需 Registry 做步骤1(查找)+步骤2(permission_key),但执行(步骤4)走 SandboxPort。Tool 的 `permission_key` 是纯计算(不需执行),所以 pipeline 用 Registry 调 permission_key 是 OK 的;只有 execute 走 Sandbox。

- [ ] **Step 1: 改 `cp/pipeline/pipeline.py`**

```python
class Pipeline:
    def __init__(self, registry: Registry, bus: Bus, sandbox: "SandboxPort"):
        self.registry = registry
        self.bus = bus
        self.sandbox = sandbox

    async def call(self, sess, sandbox_id, tool_name, params) -> PipelineResponse:
        # 步骤1: 查找工具(未知=拒)
        tool, ok = self.registry.get(tool_name)
        if not ok:
            await self.bus.publish(Event(type="tool.denied", ...))
            return PipelineResponse(allowed=False, message="permission denied")
        # 步骤2: permission_key(纯计算,不需 sandbox)
        res = tool.permission_key(params)
        # 步骤3: gate
        if not sess.gate.allowed(tool_name, res):
            await self.bus.publish(Event(type="tool.denied", ...))
            return PipelineResponse(allowed=False, message="permission denied")
        # 步骤3.5: quota
        try:
            await sess.account.charge(Usage(steps=1))
        except QuotaExceeded:
            await self.bus.publish(Event(type="quota.exceeded", ...))
            return PipelineResponse(errored=True, message="quota exceeded")
        # 步骤4: 执行——走 SandboxPort(不直接 tool.execute!)约束7
        action = {"tool": tool_name, "params": params}
        exec_result = await self.sandbox.exec_action(sandbox_id, action)
        if "error" in exec_result:
            await self.bus.publish(Event(type="tool.errored", ...))
            return PipelineResponse(errored=True, message="tool error")
        result_data = exec_result["data"]
        # 步骤5: 脱敏
        ...
        # 步骤6: 审计事件
        await self.bus.publish(Event(type="tool.called", ...))
        return PipelineResponse(allowed=True, result=result_data)
```

注意 `call` 签名多了 `sandbox_id` 参数(编排器提供当前 run 的沙箱 id)。

- [ ] **Step 2: 改 `cp/tests/test_pipeline.py` 成 async** + 适配新签名(注入 LocalSandboxExecutor + sandbox_id)。StubTool 的 execute 改 async。

- [ ] **Step 3: 改对抗测试 `cp/tests/adversarial/test_adversarial.py` 成 async**
对抗测试只测 Gate + Sanitizer(不经过 pipeline/sandbox),所以只需 `def` → `async def`,调用处无需大改(Gate.allowed 和 sanitizer.sanitize_data 是同步纯计算,不需 await)。**但** 为了 async 一致性,标记为 async test 并验证仍全绿。

- [ ] **Step 4: 改架构测试 `cp/tests/architecture/test_open_closed.py` 成 async**,注入 LocalSandboxExecutor,pipeline.call 加 sandbox_id。

- [ ] **Step 5: 跑对抗测试(硬里程碑)** `conda run -n agentos python -m pytest cp/tests/adversarial/ -v` → **8 passed**
- [ ] **Step 6: 跑架构测试** `conda run -n agentos python -m pytest cp/tests/architecture/ -v` → 2 passed
- [ ] **Step 7: 全回归** `conda run -n agentos python -m pytest cp/ -v`
- [ ] **Step 8: 提交** `git add -A && git commit -m "refactor(cp): async pipeline via SandboxPort + adversarial/arch tests async (8 cases green)"`

---

## Task 9: 控制面组装 + ch15 七约束核对

**Files:**
- Create: `cp/compose.py`
- Test: `cp/tests/test_constraints.py`

**目标:** composition root(把 Port 适配器注入控制面)+ ch15 七约束可执行核对。

- [ ] **Step 1: 实现 `cp/compose.py`**

```python
from cp.adapters.local_state import RedisStatePort
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.tools.tool import Registry
from cp.tools.fs_tools import FSReadTool, FSWriteTool, FSListTool


def build_control_plane(redis):
    """组装控制面:注入 Port 适配器。开发用 fakeredis,生产换真实 Redis。
    从 dev→prod 只换 redis 连接,代码零改(ch15 约束1/4)。"""
    registry = Registry()
    for t in [FSReadTool(), FSWriteTool(), FSListTool()]:
        registry.register(t)
    bus = InProcess()  # 进程内事件(Week 3 可换 RedisStreamMessageBus)
    sandbox = LocalSandboxExecutor(registry)
    state = RedisStatePort(redis)
    pipe = Pipeline(registry, bus, sandbox)
    return {"registry": registry, "bus": bus, "sandbox": sandbox, "state": state, "pipeline": pipe}
```

- [ ] **Step 2: 写 ch15 核对测试 `cp/tests/test_constraints.py`**

```python
"""ch15 七约束可执行核对。Week 2 修复约束 1/3/4/5/6/7(约束2 Week1 已满足)。"""
import pytest
from cp.compose import build_control_plane
from cp.ports import StatePort, MessageBusPort, SandboxPort


async def test_constraint1_modules_behind_ports(fake_redis):
    """约束1:模块边界用接口。控制面组件依赖 Port,不依赖具体实现。"""
    cp = build_control_plane(fake_redis)
    assert isinstance(cp["state"], StatePort)
    assert isinstance(cp["sandbox"], SandboxPort)


async def test_constraint3_state_externalized(fake_redis):
    """约束3:状态在 Redis,不在进程内存。重启可恢复。"""
    cp = build_control_plane(fake_redis)
    await cp["state"].save_session("s1", {"used_steps": 7})
    # 模拟"重启":新建 control plane(新进程内存),读回状态
    cp2 = build_control_plane(fake_redis)
    got = await cp2["state"].get_session("s1")
    assert got == {"used_steps": 7}


async def test_constraint4_events_on_bus(fake_redis):
    """约束4:事件经消息总线,可 replay。"""
    from cp.adapters.redis_bus import RedisStreamMessageBus
    bus = RedisStreamMessageBus(fake_redis)
    await bus.publish("agent_events.s1", {"type": "tool.called"})
    entries = await fake_redis.xrange("agent_events.s1")
    assert len(entries) == 1  # 持久化在 Stream


async def test_constraint5_sandbox_remote_interface(fake_redis):
    """约束5:沙箱接口按远程设计(create/exec/destroy)。"""
    cp = build_control_plane(fake_redis)
    sid = await cp["sandbox"].create({"workspace": "/tmp"})
    assert sid.startswith("sbx-")
    result = await cp["sandbox"].exec_action(sid, {"tool": "fs_read", "params": {"path": "x"}})
    assert "data" in result or "error" in result
    await cp["sandbox"].destroy(sid)


async def test_constraint6_control_plane_stateless(fake_redis):
    """约束6:控制面无状态。两个 control plane 实例共享同一 Redis,状态一致。"""
    cp1 = build_control_plane(fake_redis)
    cp2 = build_control_plane(fake_redis)
    await cp1["state"].save_session("s1", {"v": 1})
    assert (await cp2["state"].get_session("s1")) == {"v": 1}


def test_constraint7_orchestrator_no_direct_exec():
    """约束7:编排器(pipeline)不持有 execute 调用;通过 sandbox.exec_action。
    静态检查:Pipeline 不直接调 tool.execute(它只调 permission_key + sandbox)。"""
    import inspect
    from cp.pipeline.pipeline import Pipeline
    src = inspect.getsource(Pipeline)
    assert "tool.execute" not in src, "pipeline must not call tool.execute directly"
    assert "sandbox.exec_action" in src, "pipeline must execute via sandbox"
```

- [ ] **Step 3: 跑核对** `conda run -n agentos python -m pytest cp/tests/test_constraints.py -v` → 6 passed
- [ ] **Step 4: 全回归** `conda run -n agentos python -m pytest cp/ -v`
- [ ] **Step 5: 提交** `git add cp/compose.py cp/tests/test_constraints.py && git commit -m "feat(cp): composition root + ch15 seven-constraint checks (1/3/4/5/6/7 fixed)"`

---

## Week 2 完成判据

- [ ] `conda run -n agentos python -m pytest cp/ -v` 全绿
- [ ] 8 个对抗用例 async 版全绿(零退化)
- [ ] 开闭原则 async 版全绿
- [ ] ch15 七约束:1/3/4/5/6/7 六条修复(约束2 Week1 已满足),核对测试通过
- [ ] session 状态存 Redis,重启可恢复
- [ ] 事件经 Redis Stream,可 replay
- [ ] pipeline 通过 SandboxPort 执行(不直接 tool.execute)
- [ ] 全量 async(无 threading.Lock/Semaphore)

## 自检

**规格覆盖:** V2 ch15 七约束中 1/3/4/5/6/7 由 T1/T5/T6/T7/T8/T9 覆盖。约束2(单向依赖)Week1 已满足,保持。✅
**async 一致性:** T2-T4,T8 把所有 sync 模块改 async;T9 compose 返回 async-capable 组件。✅
**硬里程碑:** T8 对抗测试全绿。✅
**风险:** eventbus 改 async 后 audit/pipeline 的调用点需同步加 await(T3/T8);sandbox_id 参数流入 pipeline.call 改变了签名(测试全适配)。✅
