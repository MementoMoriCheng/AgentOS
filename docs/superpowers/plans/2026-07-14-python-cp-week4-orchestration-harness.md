# Week 4 — Agent Loop + 多 Agent 编排 + Harness 适配器 + 端到端

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 把前三周的积木(安全内核 + async 控制面 + 7 原语)组装成能跑的 agent:Agent Loop(大 ReAct)+ 多 agent 编排(Pipeline/Router)+ Harness 适配器(Profile + 映射表 + Router)+ 真实 LLM 接入(DeepSeek async,可选)+ 端到端数据分析 demo。

**Architecture:** Agent Loop 是 V2 ch27 的 Layer 1(大 ReAct):`while not done: llm(推理) → 原语执行 → 观察 → 再 llm`。编排模式在 Loop 之上:Pipelines 顺序链(A→B→C),Router 并行扇出+聚合。Harness Profile(YAML)描述框架编排风格,映射表把框架工具翻译成原语。真实 LLM 用 AsyncOpenAI(DeepSeek base_url);无 key 或测试时用 mock。

**Tech Stack:** Python asyncio / AsyncOpenAI(DeepSeek)/ fakeredis / pytest-asyncio

**硬里程碑:** T8 端到端 demo(mock LLM)跑通 + 8 对抗用例全绿 + 全回归。

---

## 文件结构(Week 4 新增)

```
cp/
├── agent_loop.py           # 【新】大 ReAct 循环(Layer 1)
├── orchestration/          # 【新】多 agent 编排
│   ├── __init__.py
│   ├── pipeline.py         # 顺序链 A→B→C
│   └── router.py           # fan-out/fan-in
├── llm/                    # 【新】真实 LLM 接入
│   ├── __init__.py
│   ├── deepseek.py         # AsyncDeepSeekClient
│   └── mock.py             # MockLLMClient(测试用)
├── harness/                # 【新】Harness 适配器
│   ├── __init__.py
│   ├── profile.py          # Profile YAML 加载
│   ├── mapping.py          # 框架→原语映射
│   └── router.py           # 按任务类型路由 Profile
└── tests/
    ├── test_agent_loop.py
    ├── test_orchestration.py
    ├── test_harness.py
    └── test_e2e_demo.py    # 端到端(mock LLM)
```

---

## 任务总览

| # | 任务 | 验收标准 |
|---|------|---------|
| T1 | MockLLMClient + Agent Loop(大 ReAct) | Loop 用 mock llm 跑通推理→原语→观察循环 |
| T2 | AsyncDeepSeekClient + llm 原语真实实现 | 有 key 时真实调用;无 key 回退 mock |
| T3 | 编排 Pipeline(顺序链) | A→B→C 链;前一个输出是后一个输入 |
| T4 | 编排 Router(fan-out/fan-in) | 并行多 agent + 聚合 |
| T5 | Harness Profile YAML + 加载器 | 加载 profile;注入 system prompt |
| T6 | 框架映射表(claude_mapping.yaml) | Claude 工具→原语映射 |
| T7 | Harness Router(按任务类型路由) | 代码任务→claude-style |
| T8 | 端到端 demo(mock)+ 对抗回归(硬里程碑) | 数据分析任务跑通;8 对抗全绿 |
| T9 | compose 整合编排层 + 最终验证 | 全控制面组装;全回归绿 |

---

## Task 1: MockLLMClient + Agent Loop

**Files:**
- Create: `cp/llm/__init__.py`, `cp/llm/mock.py`
- Create: `cp/agent_loop.py`
- Test: `cp/tests/test_agent_loop.py`

### `cp/llm/mock.py`:
```python
from typing import Any, Dict, List


class MockLLMClient:
    """测试用 mock LLM。按预设脚本返回响应(支持多轮)。
    每次调用返回 scripts[cursor],cursor 递增。"""

    def __init__(self, scripts: List[Dict[str, Any]]):
        """scripts: 预设响应列表。每个是 {content, tool_calls?}。"""
        self._scripts = scripts
        self._cursor = 0
        self.calls = []  # 记录所有调用(messages 快照)

    async def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict[str, Any]:
        self.calls.append(list(messages))
        if self._cursor >= len(self._scripts):
            return {"role": "assistant", "content": "[mock] done"}
        resp = self._scripts[self._cursor]
        self._cursor += 1
        return resp
```

### `cp/agent_loop.py`:
```python
"""V2 ch27 Layer 1:大 ReAct 循环。
while not done: llm(推理) → 原语执行 → 观察 → 再 llm → 直到无 tool_call。"""
import json
from typing import Any, Dict, List

from cp.primitives.registry import PrimitiveContext


async def run_agent_loop(
    task: str,
    llm,
    executor,
    sess,
    ctx: PrimitiveContext,
    primitive_schemas: List[Dict[str, Any]],
    max_steps: int = 20,
) -> Dict[str, Any]:
    """Agent Loop。llm 推理 → 原语执行 → 观察 → 循环。
    返回 {final_answer, steps_used, termination}。"""
    system_prompt = (
        "You are an autonomous agent. You have access to primitives (tools). "
        "Call a tool to accomplish the task. When done, respond with plain text."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    for step in range(max_steps):
        steps_used = step + 1
        assistant = await llm.chat(messages, primitive_schemas)
        messages.append(assistant)

        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            final_answer = assistant.get("content", "(no content)")
            break
    else:
        termination = "step_limit"
        final_answer = f"Reached step limit ({max_steps})."

    return {"final_answer": final_answer, "steps_used": steps_used, "termination": termination}
```

注:Week 4 MVP 简化 Agent Loop——先不加原语执行反馈(完整 ReAct 需要 LLM 输出 tool_call → 执行原语 → 把结果加回 messages)。**T1 先做"无工具调用的单轮/多轮推理"**(llm 返回 content 直接结束)。T8 端到端时加原语执行反馈。这样 T1 可独立测试。

实际上为了端到端能跑,Agent Loop 需要处理 tool_calls。让我在 T1 就做完整版:

```python
async def run_agent_loop(task, llm, executor, sess, ctx, primitive_schemas, max_steps=20):
    system_prompt = "You are an autonomous agent. Call primitives to accomplish the task."
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": task}]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    for step in range(max_steps):
        steps_used = step + 1
        assistant = await llm.chat(messages, primitive_schemas)
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            final_answer = assistant.get("content", "(no content)")
            break
        # 执行每个原语调用
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            resp = await executor.call(sess, ctx, name, args)
            if resp.errored:
                content = f"Error: {resp.message}"
            elif not resp.allowed:
                content = resp.message
            else:
                content = json.dumps(resp.result, default=str)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": content})
    else:
        termination = "step_limit"
        final_answer = f"Reached step limit ({max_steps})."

    return {"final_answer": final_answer, "steps_used": steps_used, "termination": termination}
```

### Test `cp/tests/test_agent_loop.py`:
```python
import json
import tempfile
from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.llm.mock import MockLLMClient
from cp.agent_loop import run_agent_loop
from cp.policy.policy import Policy, Rule
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session


class MockSandbox:
    async def create(self, config): return "sbx"
    async def exec_action(self, sid, action):
        if action.get("tool") == "fs_read":
            return {"data": {"content": "42"}}
        return {"data": {}}
    async def destroy(self, sid): pass


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
                         "function": {"name": "read", "arguments": json.dumps({"source": "file:///data/x"})}}]},
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
    # llm 永远返回 tool_calls,永不结束
    llm = MockLLMClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"tc{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}}
        ]} for i in range(30)
    ])
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        executor = PrimitiveExecutor(reg, bus)
        pol = Policy(permissions=[Rule("path", "/**", ["read"])], max_steps=3, max_tokens=1000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=None)
        result = await run_agent_loop("loop forever", llm, executor, sess, ctx, [], max_steps=3)
        assert result["termination"] == "step_limit"
```

注:test_loop_step_limit 可能因 quota(max_steps=3)先触发——但 loop 不检查 quota(那是 executor 的事)。loop 跑到 max_steps=3 终止。quota 在 executor 内:第 3 步 charge 会超限 → executor 返回 errored → loop 把 error 加进 messages → 继续。所以 loop 仍到 step_limit。OK。

提交:`feat(cp): MockLLMClient + Agent Loop (Layer 1 ReAct)`

---

## Task 2: AsyncDeepSeekClient + llm 原语真实实现

**Files:**
- Create: `cp/llm/deepseek.py`
- Modify: `cp/primitives/llm.py`(支持注入真实 client)
- Test: `cp/tests/test_deepseek.py`(有 key 标记 integration,默认 skip)

### `cp/llm/deepseek.py`:
```python
import os
from typing import Any, Dict, List, Optional

try:
    from openai import AsyncOpenAI, RateLimitError
    _OPENAI = True
except ImportError:
    _OPENAI = False


class AsyncDeepSeekClient:
    """DeepSeek async 客户端(OpenAI 兼容)。有 key 时真实调用。"""

    def __init__(self, model: str = "deepseek-chat", api_key: Optional[str] = None):
        if not _OPENAI:
            raise ImportError("openai package required")
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
        self._model = model

    async def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        resp = await self._client.chat.completions.create(
            model=self._model, messages=messages, tools=tools or None,
        )
        msg = resp.choices[0].message
        out = {"role": "assistant"}
        if msg.content:
            out["content"] = msg.content
        if msg.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return out
```

### Modify `cp/primitives/llm.py`:
LlmPrimitive 增加可选 client 注入。默认 mock;有 client 时调真实 client。

```python
class LlmPrimitive:
    name = "llm"

    def __init__(self, client=None):
        """client: 可选 LLM 客户端(有 chat 方法)。None 时用 mock。"""
        self._client = client

    # schema/permission_key 不变

    async def execute(self, ctx, params):
        if self._client is not None:
            return await self._call_real(params)
        return await self._call_mock(params)

    async def _call_real(self, params):
        messages = params.get("messages", [])
        result = await self._client.chat(messages)
        return PrimitiveResult(status="success", data={
            "content": result.get("content", ""), "tool_calls": result.get("tool_calls", []),
        })

    async def _call_mock(self, params):
        messages = params.get("messages", [])
        last = messages[-1] if messages else {}
        text = last.get("content", "") if isinstance(last, dict) else str(last)
        return PrimitiveResult(status="success", data={
            "content": f"[mock llm] echo: {text[:50]}",
            "model": params.get("model", "mock"),
        })
```

### Test: 标记 integration(默认 skip,有 key 时手动跑)
```python
import os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("DEEPSEEK_API_KEY"), reason="no DEEPSEEK_API_KEY")

async def test_deepseek_real_call():
    from cp.llm.deepseek import AsyncDeepSeekClient
    client = AsyncDeepSeekClient()
    result = await client.chat([{"role": "user", "content": "Say hello in one word."}])
    assert "content" in result
```

提交:`feat(cp): AsyncDeepSeekClient + llm primitive real impl`

---

## Task 3: 编排 Pipeline(顺序链)

**Files:**
- Create: `cp/orchestration/__init__.py`, `cp/orchestration/pipeline.py`
- Test: `cp/tests/test_orchestration.py`

### Pipeline(顺序):agent A 输出 → agent B 输入 → agent C 输出
```python
async def run_pipeline(agents, initial_input, ...):
    """顺序执行 agents;每个的 final_answer 是下一个的 task。"""
    current = initial_input
    results = []
    for i, agent_fn in enumerate(agents):
        result = await agent_fn(current)
        results.append(result)
        current = result["final_answer"]
    return {"stages": results, "final": results[-1]["final_answer"]}
```

agent_fn 是一个 async 函数:(task) → {final_answer, steps_used, termination}。用 run_agent_loop 包装。

---

## Task 4: 编排 Router(fan-out/fan-in)

**Files:** `cp/orchestration/router.py`

Router:并行跑多个 agent,聚合结果。
```python
async def run_router(agents, task, aggregator=None):
    """并行 fan-out;聚合 fan-in。"""
    results = await asyncio.gather(*[agent_fn(task) for agent_fn in agents])
    if aggregator:
        return await aggregator(results)
    return {"sub_results": results, "final": " | ".join(r["final_answer"] for r in results)}
```

---

## Task 5: Harness Profile YAML + 加载器

**Files:** `cp/harness/__init__.py`, `cp/harness/profile.py`, test

### Profile YAML 格式(V2 ch22):
```yaml
# examples/harness/claude_style.yaml
name: claude-style
description: |
  Claude Code style orchestration. Strong control, SubAgent mode.
  Maps: Bash→exec, Read→read(file://), Write→write(file://).
system_prompt_template: |
  You are a coding agent. Use primitives to accomplish tasks.
  Available: exec, read, write.
safety_rules:
  - no shell injection
  - path whitelist enforced
primitive_mappings:
  Bash: exec
  Read: "read(source=file://{path})"
  Write: "write(target=file://{path}, data={content})"
```

### 加载器:
```python
@dataclass
class HarnessProfile:
    name: str
    description: str
    system_prompt_template: str
    safety_rules: List[str]
    primitive_mappings: Dict[str, str]

def load_profile(path: str) -> HarnessProfile: ...
```

---

## Task 6: 框架映射表 + 映射器

**Files:** `cp/harness/mapping.py`, `examples/harness/claude_style.yaml`, test

映射器:框架工具调用 → 原语调用。如 `Bash(command="ls")` → `exec(command="ls")`。

---

## Task 7: Harness Router

**Files:** `cp/harness/router.py`, test

按任务类型路由到 Profile:
```python
class HarnessRouter:
    def route(self, task: str) -> HarnessProfile:
        if "code" in task.lower() or "refactor" in task.lower():
            return self._profiles["claude-style"]
        return self._profiles["default"]
```

---

## Task 8: 端到端 demo(mock)+ 对抗回归(硬里程碑)

**Files:** `cp/tests/test_e2e_demo.py`

端到端:用 mock LLM 跑一个数据分析任务(read CSV → 计算总和 → write 结果)。经完整控制面(compose + Agent Loop + 原语)。

对抗回归:8 对抗全绿。

提交:`test(cp): e2e demo (mock LLM) + adversarial regression`

---

## Task 9: compose 整合编排层 + 最终验证

**Modify:** `cp/compose.py` 增加 orchestration + harness。

全回归 + push。

---

## Week 4 完成判据

- [ ] `pytest cp/` 全绿
- [ ] Agent Loop 用 mock LLM 跑通(推理→原语→观察)
- [ ] Pipeline 顺序链 + Router fan-out/fan-in 可工作
- [ ] Harness Profile 加载 + 映射 + 路由
- [ ] 真实 LLM 有 key 时可调(集成测试默认 skip)
- [ ] 端到端 demo(mock)跑通数据分析任务
- [ ] 8 对抗用例全绿(硬里程碑)
- [ ] 零 TODO/FIXME
