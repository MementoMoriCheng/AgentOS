# Week 3 — 执行面 + 原语层 + 故障恢复

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 实现 V2 的 7 个原子原语(exec/read/write/llm/io/pub/sub)+ 4 个复合操作(spawn_agent/compress_context/generate_skill/handoff)+ URL scheme(file://kv://)+ DockerExecutor(可 skip)+ checkpoint 故障恢复。每个原语经过 6 步安全管道。

**Architecture:** 原语是控制面唯一认识的"货币"——它不认识 Claude 的 Bash、Hermes 的 exec,只认原语。每个原语实现为"经安全管道的执行单元":lookup→perm→quota→exec(via Sandbox)→sanitize→audit。read/write 用 URL scheme 统一 file/kv/vector 存储。复合操作是固定骨架脚本(外层 1 调用 + 内层 ReAct)。DockerExecutor 作为 SandboxPort 第二实现(无 Docker 时 skip)。LocalSandboxExecutor(Week 2)承载原语执行。

**Tech Stack:** Python asyncio / fakeredis / docker-py(可选,可 skip)/ redis.asyncio

**硬里程碑:** Task 9 的原语端到端测试 + Task 10 的复合操作骨架测试通过;Task 11 的对抗用例在新原语路径下仍全绿。

---

## V2 原语对照(Week 3 实现范围)

| 原语 | 类别 | 实现 | 说明 |
|------|------|------|------|
| `exec` | 执行 | 真实(走 Sandbox) | 沙箱内执行命令 |
| `read` | 读 | 真实(URL scheme) | file://kv://vector:// |
| `write` | 写 | 真实(URL scheme) | file://kv:// |
| `llm` | 推理 | mock | 返回固定响应;真实接入留 Week 4 |
| `io` | 通信 | mock | HTTP stub |
| `pub` | 发布 | 真实(Redis Stream) | 经 MessageBusPort |
| `sub` | 订阅 | 真实(Redis Stream) | 经 MessageBusPort |

| 复合操作 | 骨架 | 实现 |
|----------|------|------|
| `spawn_agent` | pub→session_create→子 ReAct→pub | 固定骨架 + 内层 mock llm |
| `compress_context` | llm(摘要)→write(kv) | 固定骨架 |
| `generate_skill` | llm(审查)→write(file)→read(list) | 固定骨架 |
| `handoff` | read(kv)→pub(handoff) | 固定骨架 |

---

## 文件结构(Week 3 新增)

```
cp/
├── primitives/             # 【新】7 原语 + 4 复合操作
│   ├── __init__.py
│   ├── registry.py         # 原语注册表(类似 Tool Registry)
│   ├── exec.py             # exec 原语
│   ├── read.py             # read 原语(URL scheme 路由)
│   ├── write.py            # write 原语(URL scheme 路由)
│   ├── llm.py              # llm 原语(mock)
│   ├── io.py               # io 原语(mock HTTP)
│   ├── pub.py              # pub 原语(经 MessageBusPort)
│   ├── sub.py              # sub 原语(经 MessageBusPort)
│   └── composite.py        # 4 复合操作(spawn/compress/generate/handoff)
├── adapters/
│   ├── docker_sandbox.py   # 【新】DockerExecutor(无 Docker 时 skip)
│   └── (local_sandbox.py 已有)
├── checkpoint.py           # 【新】快照 + 重水合(故障恢复)
└── tests/
    ├── primitives/         # 原语单测
    ├── test_composite.py
    ├── test_docker_sandbox.py  # skip 守护
    └── test_checkpoint.py
```

---

## 任务总览

| # | 任务 | 验收标准 |
|---|------|---------|
| T1 | 原语注册表 + exec/read/write(核心) | 3 原语单测通过;read/write URL scheme 路由正确 |
| T2 | llm/io mock 原语 | 2 原语单测通过 |
| T3 | pub/sub 原语(经 Redis Stream) | 2 原语单测通过;事件经 MessageBusPort |
| T4 | 4 复合操作(固定骨架) | 复合操作骨架测试通过;spawn_agent 内层 ReAct |
| T5 | DockerExecutor(可 skip) | 无 Docker 时测试 skip;有 Docker 时 create/exec/destroy |
| T6 | checkpoint 快照 + 重水合 | 沙箱死亡→读 checkpoint→续跑 |
| T7 | 原语经安全管道集成 | 原语走 pipeline 6 步;权限/配额/脱敏/审计生效 |
| T8 | 原语端到端 + 对抗回归 | **8 对抗用例全绿(硬里程碑)** |
| T9 | compose 整合原语层 | build_control_plane 含原语注册表 |

---

## Task 1: 原语注册表 + exec/read/write

**Files:**
- Create: `cp/primitives/__init__.py`
- Create: `cp/primitives/registry.py`
- Create: `cp/primitives/exec.py`
- Create: `cp/primitives/read.py`
- Create: `cp/primitives/write.py`
- Test: `cp/tests/primitives/__init__.py`, `cp/tests/primitives/test_exec_read_write.py`

- [ ] **Step 1: 原语注册表 `cp/primitives/registry.py`**

原语类似 Tool 但语义不同:原语是"控制面唯一货币",每个原语有 name/schema/permission_key/execute(经 Sandbox)。复用 Tool Protocol 思路但独立定义(原语不从 LLM schema 来,它是固定的 7 个)。

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from cp.resource import Resource


@dataclass
class PrimitiveResult:
    status: str  # "success" | "error" | "timeout"
    data: Dict[str, Any] = None
    error: str = ""


class Primitive(Protocol):
    """原语:控制面唯一认识的执行货币。每个原语经安全管道执行。
    V2 ch23:7 个原子原语 + 4 复合操作。"""
    name: str

    def schema(self) -> Dict[str, Any]: ...
    def permission_key(self, params: Dict[str, Any]) -> Resource: ...
    async def execute(self, ctx: "PrimitiveContext", params: Dict[str, Any]) -> PrimitiveResult: ...


class PrimitiveContext:
    """原语执行上下文:持有 session/sandbox_id/bus/state 等依赖。"""
    def __init__(self, session, sandbox_id, sandbox, bus, state):
        self.session = session
        self.sandbox_id = sandbox_id
        self.sandbox = sandbox
        self.bus = bus
        self.state = state


class PrimitiveRegistry:
    """原语注册表。7 原语 + 4 复合操作启动时注册。"""
    def __init__(self):
        self._prims: Dict[str, Primitive] = {}

    def register(self, p: Primitive) -> None:
        self._prims[p.name] = p

    def get(self, name: str):
        p = self._prims.get(name)
        return (p, p is not None)

    def names(self) -> List[str]:
        return list(self._prims.keys())
```

- [ ] **Step 2: exec 原语 `cp/primitives/exec.py`**

exec 在沙箱内执行命令。经 SandboxPort。

```python
from typing import Any, Dict
from cp.primitives.registry import Primitive, PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class ExecPrimitive:
    name = "exec"

    def schema(self) -> Dict[str, Any]:
        return {"name": "exec", "description": "Execute shell command in sandbox.",
                "parameters": {"type": "object",
                               "properties": {"command": {"type": "string"},
                                              "workdir": {"type": "string"}},
                               "required": ["command"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        # exec 的权限资源是 "shell" 类型;具体命令在沙箱内
        return Resource(type="shell", id=params.get("command", ""))

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        command = params.get("command", "")
        workdir = params.get("workdir", "/workspace")
        result = await ctx.sandbox.exec_action(ctx.sandbox_id,
                                               {"tool": "shell", "params": {"command": command, "workdir": workdir}})
        if "error" in result:
            return PrimitiveResult(status="error", error=result["error"])
        return PrimitiveResult(status="success", data=result.get("data", {}))
```

注:LocalSandboxExecutor 当前只认注册的 Tool。"shell" 工具需要加(或 exec 直接调 sandbox 的扩展接口)。**Week 3 简化:** 给 LocalSandboxExecutor 加一个 `exec_command(sid, command)` 方法,exec 原语调它(Docker 版本真正跑 shell,Local 版本用 subprocess mock 或直接拒绝——MVP Local 不跑任意命令)。测试用 mock sandbox。

- [ ] **Step 3: read/write 原语(URL scheme) `cp/primitives/read.py`, `cp/primitives/write.py`**

read/write 用 `source`/`target` URL 路由:`file://`→沙箱文件系统,`kv://`→Redis StatePort。

`cp/primitives/read.py`:
```python
import urllib.parse
from typing import Any, Dict
from cp.primitives.registry import PrimitiveResult, PrimitiveContext
from cp.resource import Resource


class ReadPrimitive:
    name = "read"

    def schema(self) -> Dict[str, Any]:
        return {"name": "read", "description": "Read from a location via URL scheme.",
                "parameters": {"type": "object",
                               "properties": {"source": {"type": "string"}},
                               "required": ["source"]}}

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        source = params.get("source", "")
        parsed = urllib.parse.urlparse(source)
        scheme = parsed.scheme or "file"
        # file:// → path 资源;kv:// → kv 资源
        if scheme == "file":
            return Resource(type="path", id=parsed.path)
        return Resource(type=scheme, id=parsed.netloc + parsed.path)

    async def execute(self, ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
        source = params.get("source", "")
        parsed = urllib.parse.urlparse(source)
        scheme = parsed.scheme or "file"
        if scheme == "file":
            result = await ctx.sandbox.exec_action(ctx.sandbox_id,
                                                   {"tool": "fs_read", "params": {"path": parsed.path}})
            if "error" in result:
                return PrimitiveResult(status="error", error=result["error"])
            return PrimitiveResult(status="success", data=result.get("data", {}))
        elif scheme == "kv":
            key = parsed.netloc + parsed.path
            data = await ctx.state.get_session(key)  # MVP:复用 StatePort 做 KV
            return PrimitiveResult(status="success", data={"value": data})
        return PrimitiveResult(status="error", error=f"unsupported scheme: {scheme}")
```

write 类似(target, data, mode)。

- [ ] **Step 4: 测试 `cp/tests/primitives/test_exec_read_write.py`**

用 mock sandbox(返回预设结果)+ fake_redis。测:
- exec 调 sandbox.exec_action,返回成功
- read file:// 路由到 fs_read
- read kv:// 路由到 state.get_session
- write file:// 路由到 fs_write
- read 不支持 scheme 报错

- [ ] **Step 5:** 跑测试、回归、提交
`git add cp/primitives/ cp/tests/primitives/ && git commit -m "feat(cp): primitive registry + exec/read/write (URL scheme)"`

---

## Task 2: llm/io mock 原语

**Files:** `cp/primitives/llm.py`, `cp/primitives/io.py`, test

- [ ] **llm mock:** 返回固定响应 `{"content": "[mock llm response]", "tokens": 10}`。permission_key type="llm"。schema 含 model/messages。
- [ ] **io mock:** 返回固定 `{"status": 200, "body": "[mock]"}`。permission_key type="http_url",id=endpoint。
- [ ] **测试:** llm 返回 mock 响应;io 返回 mock 响应;两者 permission_key 正确。
- [ ] 提交 `feat(cp): llm/io primitives (mock impl)`

---

## Task 3: pub/sub 原语(经 Redis Stream)

**Files:** `cp/primitives/pub.py`, `cp/primitives/sub.py`, test

- [ ] **pub:** `pub(ctx, {topic, payload})` → `ctx.bus.publish(topic, payload)`。permission type="topic"。
- [ ] **sub:** `sub(ctx, {topic, handler_desc})` → 注册一个 async handler,返回订阅成功。permission type="topic"。
- [ ] **测试(用 RedisStreamMessageBus + fake_redis):** pub 事件到 Stream;sub 收到事件。
- [ ] 提交 `feat(cp): pub/sub primitives via MessageBusPort`

---

## Task 4: 4 复合操作(固定骨架)

**Files:** `cp/primitives/composite.py`, `cp/tests/test_composite.py`

复合操作不是原语,是"原语序列脚本"。骨架固定,内容动态。

- [ ] **spawn_agent:** `pub(agent.created) → session_create(scope) → [子 ReAct: 用原语] → pub(agent.completed)`。内层用 mock llm。
- [ ] **compress_context:** `llm(model, 摘要历史) → write(kv://session/context, 摘要)`。
- [ ] **generate_skill:** `llm(审查) → write(file://skills/{name}) → read(file://skills/, list_mode)`。
- [ ] **handoff:** `read(kv://session/context) → pub(agent.handoff)`。
- [ ] **测试:** 每个复合操作的骨架步骤被调用(pub/write 被触发);内层 llm 是 mock。
- [ ] 提交 `feat(cp): 4 composite operations (spawn/compress/generate_skill/handoff)`

---

## Task 5: DockerExecutor(可 skip)

**Files:** `cp/adapters/docker_sandbox.py`, `cp/tests/test_docker_sandbox.py`

- [ ] **DockerExecutor:** 实现 SandboxPort。create→docker run(基础镜像);exec_action→docker exec;destroy→docker rm。需要 docker-py。
- [ ] **skip 守护:** 测试用 `pytest.mark.skipif` 检测 Docker daemon 不在则跳过。
- [ ] **fallback:** 如果 docker-py 未装或 daemon 不在,测试 skip,不阻塞。
- [ ] 提交 `feat(cp): DockerExecutor (SandboxPort, skip when no Docker)`

---

## Task 6: checkpoint 快照 + 重水合

**Files:** `cp/checkpoint.py`, `cp/tests/test_checkpoint.py`

- [ ] **Checkpoint:** 每步执行后,把 session 状态(policy_path, sanitization_path, identity, used_steps, used_tokens)+ 消息历史快照存 Redis(`checkpoint:{session_id}:{step}`)。
- [ ] **rehydrate:** 沙箱死亡→读最新 checkpoint→重建 session(从 YAML 重新加载 policy/sanitizer,恢复 account 用量)→续跑。
- [ ] **测试:** save→load→续跑;多步 checkpoint 链;最新 checkpoint 检索。
- [ ] 提交 `feat(cp): checkpoint + rehydrate (fault recovery)`

---

## Task 7: 原语经安全管道集成

**Files:** modify `cp/pipeline/pipeline.py`(或新增 primitive executor), test

- [ ] **原语经 pipeline:** 每个原语调用走 6 步:lookup→perm→quota→exec(via sandbox)→sanitize→audit。已有 pipeline 支撑;原语注册进 Registry(原语的 permission_key 让 Gate 能匹配)。
- [ ] **策略示例:** 加原语权限规则到 policy YAML(如 `exec` 需要 `shell` 资源规则)。
- [ ] **测试:** 原语经 pipeline 被拒(无权限)/被允许/审计事件触发。
- [ ] 提交 `feat(cp): primitives through security pipeline`

---

## Task 8: 原语端到端 + 对抗回归(硬里程碑)

- [ ] **端到端:** 用原语序列完成任务(如 read file:// → write file://),经 compose 组装的控制面。
- [ ] **对抗回归:** 8 对抗用例在新原语路径下仍全绿。
- [ ] 提交 `test(cp): primitive e2e + adversarial regression (8 cases green)`

---

## Task 9: compose 整合原语层

**Files:** modify `cp/compose.py`

- [ ] **build_control_plane** 注册 7 原语 + 4 复合操作到 PrimitiveRegistry。
- [ ] **测试:** compose 返回含 primitives registry;原语可经 pipeline 执行。
- [ ] 提交 `feat(cp): compose integrates primitive layer`

---

## Week 3 完成判据

- [ ] `pytest cp/` 全绿(含 skip 的 Docker 测试)
- [ ] 7 原语单测全过(exec/read/write/llm/io/pub/sub)
- [ ] 4 复合操作骨架测试全过
- [ ] read/write URL scheme(file://kv://)路由正确
- [ ] checkpoint 快照 + 重水合可工作
- [ ] 原语经安全管道(权限/配额/脱敏/审计)生效
- [ ] 8 对抗用例全绿(硬里程碑,零退化)
- [ ] DockerExecutor 在无 Docker 时 skip

## 自检

**规格覆盖:** V2 ch23 的 7 原语 + ch23.5 的 4 复合 + ch25 的 URL scheme + ch11 的 checkpoint。✅
**硬里程碑:** T8 对抗全绿。✅
**风险:** exec 原语在 Local 沙箱不能真跑 shell(MVP 安全考量);用 mock sandbox 测试。DockerExecutor 依赖 daemon。复合操作内层 ReAct 用 mock llm。✅
