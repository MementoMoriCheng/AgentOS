# Go Kernel → Python 控制面 重写实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已验证的 Go 安全内核(Kernel + Gateway + Runtime)重写为符合 V2 架构的 Python 控制面,且安全护城河(8 个对抗用例 + 开闭原则)零退化。

**Architecture:** 第一周做**忠实同步移植**——把 Go 的安全算法 1:1 翻译成 Python,用对抗测试证明零退化;第二到四周再做 V2 拓扑改造(状态外化、消息总线、沙箱池、Port 接口)。Week 1 全程保持同步语义(对应 Go 的 sync.Mutex/channel),async 转换留到 Week 2——这样第一周的唯一风险问题是"安全逻辑有没有退化",不被并发模型改造干扰。

**Tech Stack:** Python 3.11+ / pytest / pytest-asyncio(后续) / PyYAML / redis-py(Week2) / aiokafka(Week2)

**关键原则:** Week 1 的每个模块都先写从 Go 测试移植来的失败测试,再实现,再跑通。8 个对抗用例全部通过是 Week 1 的硬性里程碑——不通过不进入 Week 2。

---

## 文件结构(Go → Python 映射)

新顶层 Python 包 `cp/`(control plane),与现有 `runtime/` 并存,迁移完成后删除 `runtime/` 与 `kernel/`、`gateway/`。

```
cp/                              # 新 Python 控制面(替代 kernel/ + gateway/ + runtime/)
├── resource.py                  # ← kernel/internal/resource/resource.go
├── sandbox/
│   └── fs.py                    # ← kernel/internal/sandbox/fs.go (安全核心)
├── policy/
│   ├── policy.py                # ← kernel/internal/policy/policy.go
│   └── gate.py                  # ← kernel/internal/policy/gate.go
├── sanitize/
│   └── sanitizer.py             # ← kernel/internal/sanitize/sanitizer.go
├── tools/
│   ├── tool.py                  # ← kernel/internal/tools/tool.go (Tool Protocol + Registry)
│   └── fs_tools.py              # ← kernel/internal/tools/fs_tools.go
├── eventbus/
│   └── bus.py                   # ← kernel/internal/eventbus/bus.go
├── audit/
│   ├── ledger.py                # ← kernel/internal/audit/ledger.go (hash 链)
│   └── subscriber.py            # ← kernel/internal/audit/subscriber.go
├── session/
│   ├── session.py               # ← kernel/internal/session/session.go
│   └── account.py               # ← kernel/internal/session/account.go
├── auth/
│   ├── auth.py                  # ← kernel/internal/auth/auth.go
│   └── policy_guard.py          # ← kernel/internal/auth/policy_guard.go
├── scheduler/
│   └── scheduler.py             # ← kernel/internal/scheduler/scheduler.go
├── pipeline/
│   └── pipeline.py              # ← kernel/internal/pipeline/pipeline.go (6 步管道)
└── tests/
    ├── adversarial/             # ← kernel/test/adversarial (8 红队用例)
    └── architecture/            # ← kernel/test/architecture (开闭原则)
```

---

## 四周路线图(任务级 + 验收标准)

### Week 1 — 安全内核忠实移植(本计划详述部分)

| 任务 | 交付物 | 验收标准 |
|------|--------|---------|
| T1 脚手架 + resource | `cp/__init__.py`, `cp/resource.py` | `pytest cp/tests/test_resource.py` 通过 |
| T2 sandbox 路径解析 | `cp/sandbox/fs.py` | 穿越/符号链接/绝对路径单测全过 |
| T3 policy + gate | `cp/policy/*.py` | glob `**` 匹配 + 三元权限单测通过 |
| T4 sanitize | `cp/sanitize/sanitizer.py` | mask/hash/redact 三策略单测通过 |
| T5 tools 接口 + fs_tools | `cp/tools/*.py` | Tool Protocol + 3 个 fs 工具单测通过 |
| T6 eventbus | `cp/eventbus/bus.py` | 订阅/取消订阅/panic 隔离单测通过 |
| T7 audit hash 链 | `cp/audit/*.py` | append + verify_chain + 篡改检测单测通过 |
| T8 session + account | `cp/session/*.py` | 配额扣减 + 超限拒绝单测通过 |
| T9 auth + policy_guard | `cp/auth/*.py` | 受信目录校验单测通过 |
| T10 scheduler | `cp/scheduler/scheduler.py` | 并发上限 + 释放单测通过 |
| T11 pipeline 6 步 | `cp/pipeline/pipeline.py` | 6 步顺序 + 拒绝/审计事件单测通过 |
| **T12 对抗测试移植** | `cp/tests/adversarial/` | **8 个红队用例全部通过(硬里程碑)** |
| T13 架构测试移植 | `cp/tests/architecture/` | 开闭原则:加 db_query 工具零改核心 |

### Week 2 — V2 拓扑:状态外化 + Port + 消息总线(后续计划详述)

| 任务 | 验收标准 |
|------|---------|
| 定义 5 个 Port(SandboxPort/StatePort/MessageBusPort/AuthPort/AuditPort) | Port 是 Protocol,现有实现适配为 Local 适配器 |
| session 状态外化到 Redis | `redis.get(session:{id})` 替代内存 map;重启可恢复 |
| eventbus 接 Redis Stream | 事件可 replay;跨进程订阅 |
| audit 后端接 Kafka topic | `agent_events.{session}` 事件流可回放 |
| async 化改造 | sync → asyncio;threading.Lock → asyncio.Lock/Redis 分布式锁 |
| ch15 七约束逐条核对 | 3/4/5/6/7 五条违反项修复 |

### Week 3 — 执行面 + 原语层(后续计划详述)

| 任务 | 验收标准 |
|------|---------|
| SandboxPort 实现:LocalSandboxExecutor + DockerExecutor | create/exec/destroy;沙箱无状态 |
| 沙箱池 + Redis 注册表 + 心跳 | 30s 无心跳标 dead |
| 7 原语 exec/read/write/llm/io/pub/sub | 每个原语过 6 步安全管道 |
| read/write URL scheme(file:// kv:// vector://) | 路由正确 |
| 4 复合操作 spawn_agent/compress_context/generate_skill/handoff | 骨架固定、内容动态 |
| 故障恢复:checkpoint + 重水合 | 沙箱死亡从最近 checkpoint 续跑 |

### Week 4 — 编排 + 适配器 + 联调(后续计划详述)

| 任务 | 验收标准 |
|------|---------|
| 多 agent 编排:Pipeline/Router/Blackboard/Hub-spoke | 四模式可跑 |
| Harness Adapter Layer + Profile YAML | claude_profile.yaml 跑通 |
| 框架映射表 claude_mapping.yaml | Claude 工具映射到原语 |
| Harness Router 按任务类型路由 | 代码任务→claude-style |
| 端到端 demo 用新拓扑跑通 | 数据分析任务 + 实时控制台 |
| 90 个测试全过 + 对抗用例零退化 | 回归基线 |

---

# Week 1 详细 TDD 任务

## Task 1: 脚手架 + Resource

**Files:**
- Create: `cp/__init__.py`
- Create: `cp/resource.py`
- Create: `cp/tests/__init__.py`
- Create: `cp/tests/test_resource.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_resource.py`:
```python
from cp.resource import Resource


def test_resource_holds_type_and_id():
    r = Resource(type="path", id="examples/workspace/sales.csv")
    assert r.type == "path"
    assert r.id == "examples/workspace/sales.csv"


def test_resource_is_frozen():
    import dataclasses
    r = Resource(type="path", id="x")
    assert dataclasses.is_dataclass(r)
    try:
        r.id = "y"
        assert False, "should be frozen"
    except dataclasses.FrozenInstanceError:
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_resource.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cp'`

- [ ] **Step 3: 实现**

`cp/__init__.py`: (空文件)

`cp/resource.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    """权限判定的泛化对象。type 决定匹配哪类规则(path/db_table/http_url...),id 是具体标识。"""
    type: str
    id: str
```

`cp/tests/__init__.py`: (空文件)

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_resource.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/__init__.py cp/resource.py cp/tests/__init__.py cp/tests/test_resource.py
git commit -m "feat(cp): scaffold package + Resource dataclass"
```

---

## Task 2: sandbox 路径解析(安全核心)

**Files:**
- Create: `cp/sandbox/__init__.py`
- Create: `cp/sandbox/fs.py`
- Test: `cp/tests/test_sandbox_fs.py`

**注:** Go 的 `filepath.EvalSymlinks` 在路径不存在时报错,故有 `resolveViaExistingAncestor` 兜底;Python 的 `os.path.realpath` 对不存在路径会解析已存在前缀、追加剩余部分,行为等价于该兜底,因此 Python 版更简洁。逻辑等价性由测试保证。

- [ ] **Step 1: 写失败测试**

`cp/tests/test_sandbox_fs.py`:
```python
import os
import tempfile

import pytest

from cp.sandbox.fs import resolve, PathTraversalError


def test_resolve_normal_relative_path():
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        os.makedirs("examples/workspace/out", exist_ok=True)
        safe = resolve("examples/workspace/out/total.txt")
        assert safe.endswith("examples/workspace/out/total.txt")


def test_resolve_rejects_traversal():
    with pytest.raises(PathTraversalError):
        resolve("examples/workspace/../../../../etc/passwd")


def test_resolve_rejects_double_dot_segment():
    with pytest.raises(PathTraversalError):
        resolve("examples/workspace/out/../../../secret")


def test_resolve_rejects_absolute_unix_path():
    # 绝对路径不归 sandbox.Resolve 管(由 Gate glob 拒),但含 .. 仍要拒
    with pytest.raises(PathTraversalError):
        resolve("/etc/../etc/shadow")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_sandbox_fs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cp.sandbox.fs'`

- [ ] **Step 3: 实现**

`cp/sandbox/__init__.py`: (空文件)

`cp/sandbox/fs.py`:
```python
import os
from pathlib import PurePath


class PathTraversalError(ValueError):
    """请求路径清洗后含 ".." 段。"""


class SymlinkEscapeError(ValueError):
    """真实落点逃出所在树(符号链接逃逸)。"""


def resolve(requested: str) -> str:
    """把请求路径转成安全的绝对路径。

    拒绝:清洗后任何 ".." 段;真实落点逃出所在树的符号链接。
    Python 的 os.path.realpath 对不存在路径会解析已存在前缀,
    等价于 Go 版的 resolveViaExistingAncestor,无需单独兜底。
    """
    clean = os.path.normpath(requested)
    abs_path = os.path.abspath(clean)
    # 任何 ".." 段 = 穿越,直接拒
    if ".." in PurePath(clean).parts:
        raise PathTraversalError(f"path traversal rejected: {requested}")
    real = os.path.realpath(abs_path)
    if real != abs_path and not _is_under(real, os.path.dirname(abs_path)):
        raise SymlinkEscapeError(f"symlink escape rejected: {requested} -> {real}")
    return real


def _is_under(path: str, root: str) -> bool:
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return False
    if rel == ".":
        return True
    return ".." not in PurePath(rel).parts
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_sandbox_fs.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/sandbox/__init__.py cp/sandbox/fs.py cp/tests/test_sandbox_fs.py
git commit -m "feat(cp): sandbox path resolution (traversal + symlink escape)"
```

---

## Task 3: Policy + Gate

**Files:**
- Create: `cp/policy/__init__.py`
- Create: `cp/policy/policy.py`
- Create: `cp/policy/gate.py`
- Test: `cp/tests/test_policy_gate.py`

**注:** Go 用 `doublestar.Match` 做 glob(`**` 递归)。Python 标准库无等价物,故实现 `_glob_to_regex` 把 `**`/`*`/`?` 翻译成正则。

- [ ] **Step 1: 写失败测试**

`cp/tests/test_policy_gate.py`:
```python
from cp.policy.policy import Policy, Rule, load_from_file
from cp.policy.gate import Gate
from cp.resource import Resource


def _gate_with(rules):
    return Gate(Policy(permissions=rules, max_steps=20))


def test_gate_allows_read_under_workspace():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read", "fs_list"])])
    assert g.allowed("fs_read", Resource("path", "examples/workspace/sales.csv"))


def test_gate_denies_write_outside_out_dir():
    g = _gate_with([
        Rule("path", "examples/workspace/**", ["fs_read", "fs_list"]),
        Rule("path", "examples/workspace/out/**", ["fs_write"]),
    ])
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/sales.csv"))
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/evil.txt"))
    assert g.allowed("fs_write", Resource("path", "examples/workspace/out/total.txt"))


def test_gate_denies_absolute_path():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("fs_read", Resource("path", "/etc/shadow"))
    assert not g.allowed("fs_read", Resource("path", "C:/Windows/System32/config/SAM"))


def test_gate_denies_traversal():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    for attack in [
        "examples/workspace/../../../../etc/passwd",
        "examples/workspace/../../../.ssh/id_rsa",
        "examples/workspace/out/../../../secret",
    ]:
        assert not g.allowed("fs_read", Resource("path", attack)), attack


def test_gate_denies_unknown_action():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("shell_exec", Resource("path", "rm -rf /"))


def test_gate_denies_unknown_resource_type():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("db_query", Resource("db_table", "orders"))


def test_gate_exact_match_for_non_path_type():
    g = _gate_with([Rule("db_table", "sales.orders", ["db_query"])])
    assert g.allowed("db_query", Resource("db_table", "sales.orders"))
    assert not g.allowed("db_query", Resource("db_table", "finance.salaries"))


def test_load_from_file_reads_real_policy():
    p = load_from_file("examples/policies/data_analyst.yaml")
    assert p.agent_role == "data_analyst"
    assert p.max_steps == 20
    assert len(p.permissions) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_policy_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 policy.py**

`cp/policy/__init__.py`: (空文件)

`cp/policy/policy.py`:
```python
import os
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class Rule:
    """一条权限规则:某资源类型 + glob 模式 + 允许的动作集合。"""
    resource_type: str
    pattern: str
    actions: List[str] = field(default_factory=list)


@dataclass
class Policy:
    """授予一个 agent 会话的完整策略。"""
    agent_role: str = ""
    permissions: List[Rule] = field(default_factory=list)
    sanitization_path: str = ""
    max_steps: int = 0
    max_tokens: int = 0


def load_from_file(path: str) -> Policy:
    """从 YAML 文件加载策略。max_steps 为 0 时默认 20。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    p = Policy(
        agent_role=data.get("agent_role", ""),
        permissions=[
            Rule(r["resource_type"], r["pattern"], r.get("actions", []))
            for r in data.get("permissions", [])
        ],
        sanitization_path=data.get("sanitization_path", ""),
        max_steps=data.get("max_steps", 0),
        max_tokens=data.get("max_tokens", 0),
    )
    if p.max_steps == 0:
        p.max_steps = 20
    return p
```

- [ ] **Step 4: 实现 gate.py**

`cp/policy/gate.py`:
```python
import os
import re
from pathlib import PurePath

from cp.policy.policy import Policy
from cp.resource import Resource


class Gate:
    """按 Policy 的规则匹配 (action, resource)。不认识任何工具名,只做通用三元匹配。"""

    def __init__(self, policy: Policy):
        self.rules = policy.permissions

    def allowed(self, action: str, res: Resource) -> bool:
        for rule in self.rules:
            if rule.resource_type != res.type:
                continue
            if action not in rule.actions:
                continue
            if _match_id(rule.pattern, rule.resource_type, res.id):
                return True
        return False


def _match_id(pattern: str, resource_type: str, id_: str) -> bool:
    """按资源类型决定匹配方式。path 类型:glob + 拒穿越/绝对路径;其它:精确匹配。"""
    if resource_type == "path":
        return _match_path(pattern, id_)
    return pattern == id_


def _match_path(pattern: str, path: str) -> bool:
    # 统一正斜杠,避免 Windows 反斜杠与 glob 不匹配
    clean = os.path.normpath(path).replace(os.sep, "/")
    pattern = os.path.normpath(pattern).replace(os.sep, "/")
    if os.path.isabs(path):
        return False
    if ".." in clean.split("/"):
        return False
    return re.match(_glob_to_regex(pattern), clean) is not None


def _glob_to_regex(pattern: str) -> str:
    """把含 ** 的 glob 翻译成正则。

    **  :跨目录段匹配(零或多个段);
    *   :段内匹配(不含 /);
    ?   :单个字符(不含 /)。
    """
    i = 0
    n = len(pattern)
    out = []
    while i < n:
        if pattern[i:i + 2] == "**":
            prev = pattern[i - 1] if i > 0 else ""
            nxt = pattern[i + 2] if i + 2 < n else ""
            if nxt == "" and prev == "/":
                # /** 在末尾:可选的 /加任意
                out.append(r"(?:/.*)?")
                i += 2
            elif nxt == "/" and prev != "/" and prev != "":
                # **/ 在中间:零或多个段
                out.append(r"(?:.*/)?")
                i += 3
            else:
                out.append(r".*")
                i += 2
        elif pattern[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append(r"[^/]")
            i += 1
        elif pattern[i] == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "^" + "".join(out) + "$"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest cp/tests/test_policy_gate.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: 提交**

```bash
git add cp/policy/ cp/tests/test_policy_gate.py
git commit -m "feat(cp): policy + gate with ** glob matcher"
```

---

## Task 4: Sanitize 脱敏层

**Files:**
- Create: `cp/sanitize/__init__.py`
- Create: `cp/sanitize/sanitizer.py`
- Test: `cp/tests/test_sanitize.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_sanitize.py`:
```python
from cp.sanitize.sanitizer import Sanitizer, FieldRule, load_from_file


def test_mask_default_uses_stars():
    s = Sanitizer.new_from_rules([FieldRule(name="id_card", strategy="mask")])
    out = s.sanitize_data({"id_card": "110101199001011234"})
    assert out["id_card"] == "***"


def test_mask_keeps_prefix_suffix():
    s = Sanitizer.new_from_rules([
        FieldRule(name="phone", strategy="mask", keep_prefix=3, keep_suffix=4)
    ])
    out = s.sanitize_data({"phone": "13812341234"})
    assert out["phone"] == "138********1234"


def test_hash_returns_prefixed_hex():
    s = Sanitizer.new_from_rules([FieldRule(name="customer_id", strategy="hash")])
    out = s.sanitize_data({"customer_id": "C001"})
    assert out["customer_id"].startswith("h_")
    assert len(out["customer_id"]) == 2 + 16


def test_redact_removes_field_but_summary_records_it():
    s = Sanitizer.new_from_rules([FieldRule(name="remark", strategy="redact")])
    result = s.sanitize({"phone": "13812341234", "remark": "secret", "amount": 120})
    assert "remark" not in result.data
    fields = {f.field for f in result.summary}
    assert "remark" in fields
    assert result.data["amount"] == 120  # 非 PII 不动


def test_non_string_field_hashed():
    s = Sanitizer.new_from_rules([FieldRule(name="amount", strategy="hash")])
    out = s.sanitize_data({"amount": 120})
    assert out["amount"].startswith("h_")


def test_no_rules_passes_through():
    s = Sanitizer.new_from_rules([])
    out = s.sanitize_data({"x": 1})
    assert out == {"x": 1}


def test_load_from_file_reads_real_rules():
    s = load_from_file("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({"phone": "13812341234", "customer_id": "C001", "remark": "s", "amount": 120})
    assert out["phone"] != "13812341234"
    assert out["customer_id"] != "C001"
    assert "remark" not in out
    assert out["amount"] == 120
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_sanitize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`cp/sanitize/__init__.py`: (空文件)

`cp/sanitize/sanitizer.py`:
```python
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

_OMIT = object()  # redact 哨兵:Sanitize 检测到就跳过该字段(完全移除)


@dataclass
class FieldRule:
    name: str
    strategy: str  # mask | hash | redact
    keep_prefix: int = 0
    keep_suffix: int = 0


@dataclass
class FieldSanitization:
    """脱敏摘要的一条:字段名 + 策略,不含原始值。"""
    field: str
    strategy: str


@dataclass
class SanitizeResult:
    data: Dict[str, Any]
    summary: List[FieldSanitization] = field(default_factory=list)


class Sanitizer:
    """按字段名应用脱敏规则。规则只读,线程安全。"""

    def __init__(self, rules: Dict[str, FieldRule]):
        self.rules = rules

    @classmethod
    def new_from_rules(cls, rules: Optional[List[FieldRule]]) -> "Sanitizer":
        m = {}
        for r in (rules or []):
            m[r.name] = r
        return cls(m)

    @classmethod
    def load_from_file(cls, path: str) -> "Sanitizer":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.new_from_rules(
            [FieldRule(r["name"], r["strategy"], r.get("keep_prefix", 0), r.get("keep_suffix", 0))
             for r in data.get("fields", [])]
        )

    def sanitize(self, data: Dict[str, Any]) -> SanitizeResult:
        """对 data 中匹配规则的字段应用脱敏,返回新 data 与摘要(不改原 dict)。"""
        out: Dict[str, Any] = {}
        summary: List[FieldSanitization] = []
        for k, v in data.items():
            rule = self.rules.get(k)
            if rule is None:
                out[k] = v
                continue
            applied = self._apply(rule, v)
            summary.append(FieldSanitization(field=k, strategy=rule.strategy))
            if applied is _OMIT:
                continue  # redact:完全移除(摘要已记)
            out[k] = applied
        return SanitizeResult(data=out, summary=summary)

    def sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """便捷包装,仅返回 data。"""
        return self.sanitize(data).data

    def _apply(self, rule: FieldRule, v: Any) -> Any:
        if not isinstance(v, str):
            if rule.strategy == "hash":
                return _hash_value(v)
            return v
        if rule.strategy == "mask":
            return _mask_string(v, rule.keep_prefix, rule.keep_suffix)
        if rule.strategy == "hash":
            return _hash_string(v)
        if rule.strategy == "redact":
            return _OMIT
        return v


def _mask_string(s: str, keep_prefix: int, keep_suffix: int) -> str:
    if keep_prefix == 0 and keep_suffix == 0:
        return "***"
    if len(s) <= keep_prefix + keep_suffix:
        return "***"
    return s[:keep_prefix] + "*" * (len(s) - keep_prefix - keep_suffix) + s[len(s) - keep_suffix:]


def _hash_string(s: str) -> str:
    h = hashlib.sha256(s.encode()).hexdigest()
    return "h_" + h[:16]


def _hash_value(v: Any) -> str:
    return _hash_string(f"{v}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_sanitize.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/sanitize/ cp/tests/test_sanitize.py
git commit -m "feat(cp): sanitizer with mask/hash/redact"
```

---

## Task 5: Tool 接口 + fs_tools

**Files:**
- Create: `cp/tools/__init__.py`
- Create: `cp/tools/tool.py`
- Create: `cp/tools/fs_tools.py`
- Test: `cp/tests/test_fs_tools.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_fs_tools.py`:
```python
import json
import os
import tempfile

import pytest

from cp.tools.tool import Registry
from cp.tools.fs_tools import FSReadTool, FSWriteTool, FSListTool
from cp.resource import Resource


def test_registry_register_and_get():
    reg = Registry()
    reg.register(FSReadTool())
    t, ok = reg.get("fs_read")
    assert ok and t.name() == "fs_read"
    _, ok = reg.get("nope")
    assert not ok


def test_fs_read_permission_key():
    assert FSReadTool().permission_key({"path": "a/b"}) == Resource("path", "a/b")


def test_fs_write_writes_and_reads_back():
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        reg = Registry()
        reg.register(FSWriteTool())
        reg.register(FSReadTool())
        w, _ = reg.get("fs_write")
        r, _ = reg.get("fs_read")
        w.execute({}, {"path": "examples/workspace/out/t.txt", "content": "hi"})
        res = r.execute({}, {"path": "examples/workspace/out/t.txt"})
        assert res.data["content"] == "hi"


def test_fs_list_lists_entries():
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        os.makedirs("wd", exist_ok=True)
        open("wd/a.txt", "w").close()
        open("wd/b.txt", "w").close()
        res = FSListTool().execute({}, {"path": "wd"})
        assert set(res.data["entries"]) == {"a.txt", "b.txt"}


def test_fs_write_rejects_traversal():
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        with pytest.raises(Exception):
            FSWriteTool().execute({}, {"path": "../evil.txt", "content": "x"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_fs_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 tool.py**

`cp/tools/__init__.py`: (空文件)

`cp/tools/tool.py`:
```python
import json
from dataclasses import dataclass
from typing import Any, Dict, Protocol

from cp.resource import Resource


@dataclass
class ToolResult:
    data: Dict[str, Any]


class Tool(Protocol):
    """自描述工具。控制面不认识任何具体工具,只调这个接口。
    加新工具 = 实现这个接口 + 注册,核心零改(开闭原则)。"""

    def name(self) -> str: ...

    def schema(self) -> str:
        """给 LLM 的 function schema(JSON 字符串)。"""
        ...

    def permission_key(self, params: Dict[str, Any]) -> Resource: ...

    def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult: ...


class Registry:
    """工具注册表。"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        self._tools[t.name()] = t

    def get(self, name: str):
        t = self._tools.get(name)
        return (t, t is not None)
```

- [ ] **Step 4: 实现 fs_tools.py**

`cp/tools/fs_tools.py`:
```python
import json
import os
from pathlib import Path
from typing import Any, Dict

from cp.resource import Resource
from cp.sandbox.fs import resolve
from cp.tools.tool import ToolResult


class FSReadTool:
    def name(self) -> str:
        return "fs_read"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_read",
            "description": "Read a text file. Path is relative to the workspace root.",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        with open(safe, "r", encoding="utf-8") as f:
            content = f.read()
        return ToolResult(data={"content": content})


class FSWriteTool:
    def name(self) -> str:
        return "fs_write"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_write",
            "description": "Write text content to a file (creates parent dirs).",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"},
                                          "content": {"type": "string"}},
                           "required": ["path", "content"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        content = params.get("content", "")
        os.makedirs(os.path.dirname(safe), exist_ok=True)
        # 原子写:先写 .tmp,再 rename。崩溃时要么旧要么新,无半成品。
        tmp = safe + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, safe)
        return ToolResult(data={"bytes_written": len(content)})


class FSListTool:
    def name(self) -> str:
        return "fs_list"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_list",
            "description": "List file names in a directory.",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        names = sorted(os.listdir(safe))
        return ToolResult(data={"entries": names})
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest cp/tests/test_fs_tools.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 提交**

```bash
git add cp/tools/ cp/tests/test_fs_tools.py
git commit -m "feat(cp): Tool protocol + fs_read/fs_write/fs_list"
```

---

## Task 6: EventBus

**Files:**
- Create: `cp/eventbus/__init__.py`
- Create: `cp/eventbus/bus.py`
- Test: `cp/tests/test_eventbus.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_eventbus.py`:
```python
from cp.eventbus.bus import Event, InProcess


def test_subscribe_receives_published_event():
    bus = InProcess()
    received = []
    bus.subscribe(lambda e: received.append(e))
    bus.publish(Event(type="tool.called", session_id="s1"))
    assert len(received) == 1
    assert received[0].type == "tool.called"
    assert received[0].timestamp > 0  # publish 填充


def test_unsubscribe_stops_delivery():
    bus = InProcess()
    received = []
    unsub = bus.subscribe(lambda e: received.append(e))
    bus.publish(Event(type="x"))
    unsub()
    bus.publish(Event(type="y"))
    assert len(received) == 1


def test_handler_exception_does_not_crash_publish():
    bus = InProcess()
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    sink = []
    bus.subscribe(lambda e: sink.append(e))
    bus.publish(Event(type="x"))  # 不抛
    assert len(sink) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_eventbus.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`cp/eventbus/__init__.py`: (空文件)

`cp/eventbus/bus.py`:
```python
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class FieldSanitization:
    """脱敏摘要的一条:字段名 + 策略,不含原始值。独立定义避免循环依赖。"""
    field: str
    strategy: str  # mask | hash | redact


@dataclass
class Event:
    """Kernel 内一切值得关注的事件。"""
    type: str = ""  # tool.called | tool.denied | ... | run.* | runtime.*
    session_id: str = ""
    run_id: str = ""
    tool: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    identity: str = ""
    sanitize: List[FieldSanitization] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0


class Bus:
    """事件总线接口(Week 2 会加 Kafka/Redis Stream 实现)。"""

    def publish(self, event: Event) -> None: ...
    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]: ...


class InProcess(Bus):
    """同步分发事件给所有订阅者。订阅者异常不影响主流程。"""

    def __init__(self):
        self._mu = threading.Lock()
        self._handlers: List[Optional[Callable]] = []

    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]:
        with self._mu:
            idx = len(self._handlers)
            self._handlers.append(handler)

        def _unsub():
            with self._mu:
                if idx < len(self._handlers):
                    self._handlers[idx] = None  # 置空;publish 跳过 None

        return _unsub

    def publish(self, event: Event) -> None:
        event.timestamp = time.time_ns()
        # 快照 handlers,避免回调里改订阅列表导致的竞态
        with self._mu:
            snapshot = list(self._handlers)
        for h in snapshot:
            if h is None:
                continue
            try:
                h(event)
            except Exception:
                pass  # 订阅者异常不影响主流程
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_eventbus.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/eventbus/ cp/tests/test_eventbus.py
git commit -m "feat(cp): in-process eventbus with panic isolation"
```

---

## Task 7: Audit hash 链 + 订阅者

**Files:**
- Create: `cp/audit/__init__.py`
- Create: `cp/audit/ledger.py`
- Create: `cp/audit/subscriber.py`
- Test: `cp/tests/test_audit.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_audit.py`:
```python
import json
import os
import tempfile

from cp.audit.ledger import Ledger, Entry, verify_chain
from cp.audit.subscriber import register_audit_subscriber
from cp.eventbus.bus import Event, InProcess


def _entry(tool="fs_read", outcome="allowed"):
    return Entry(session_id="s1", tool=tool, params_json="{}", outcome=outcome, result_json="{}")


def test_append_and_read_back():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        ledger.append(_entry())
        ledger.append(_entry(tool="fs_write"))
        entries = ledger.read_all()
        assert len(entries) == 2
        assert entries[0].tool == "fs_read"
        assert entries[1].tool == "fs_write"


def test_chain_verifies_when_intact():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        ledger.append(_entry())
        ledger.append(_entry())
        assert verify_chain(ledger.read_all()) is None


def test_chain_detects_tamper():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        ledger.append(_entry())
        ledger.append(_entry())
        # 篡改第二条的 tool
        entries = ledger.read_all()
        entries[1] = Entry(session_id="s1", tool="tampered",
                           params_json="{}", outcome="allowed", result_json="{}",
                           prev_hash=entries[1].prev_hash, hash=entries[1].hash)
        err = verify_chain(entries)
        assert err is not None


def test_reload_picks_up_last_hash():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        Ledger(path).append(_entry())
        # 新实例加载已有文件,继续追加,链仍连续
        ledger2 = Ledger(path)
        ledger2.append(_entry())
        assert verify_chain(ledger2.read_all()) is None


def test_subscriber_writes_audit_for_relevant_events():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        bus = InProcess()
        register_audit_subscriber(ledger, bus)
        bus.publish(Event(type="tool.called", session_id="s1", tool="fs_read",
                          params={"path": "x"}, result={"content": "y"}))
        bus.publish(Event(type="runtime.step", session_id="s1"))  # 不审计
        entries = ledger.read_all()
        assert len(entries) == 1
        assert entries[0].tool == "fs_read"
        assert entries[0].outcome == "allowed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 ledger.py**

`cp/audit/__init__.py`: (空文件)

`cp/audit/ledger.py`:
```python
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

GENESIS_HASH = "0" * 64


@dataclass
class Entry:
    """一条被审计的事件记录。"""
    session_id: str = ""
    timestamp_nano: int = 0
    tool: str = ""
    params_json: str = ""
    outcome: str = ""  # allowed | denied | error | session_started | session_ended | quota_exceeded
    result_json: str = ""
    prev_hash: str = ""
    hash: str = ""


class Ledger:
    """append-only、hash 链的审计日志。"""

    def __init__(self, path: str):
        self._mu = threading.Lock()
        self.path = path
        self.last_hash = GENESIS_HASH
        # 若文件已存在,加载最后一条的 hash 作为链尾
        if os.path.exists(path):
            for e in self.read_all():
                self.last_hash = e.hash

    def append(self, e: Entry) -> None:
        with self._mu:
            e.timestamp_nano = time.time_ns()
            e.prev_hash = self.last_hash
            e.hash = _compute_hash(e.prev_hash, e)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(e)) + "\n")
            self.last_hash = e.hash

    def read_all(self) -> List[Entry]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(Entry(**json.loads(line)))
        return out


def verify_chain(entries: List[Entry]) -> Optional[str]:
    """重算所有 hash,任一环断裂返回错误描述;完好返回 None。"""
    prev = GENESIS_HASH
    for i, e in enumerate(entries):
        if e.prev_hash != prev:
            return f"chain broken at entry {i}: prev_hash mismatch"
        if _compute_hash(e.prev_hash, e) != e.hash:
            return f"chain broken at entry {i}: hash mismatch"
        prev = e.hash
    return None


def _compute_hash(prev: str, e: Entry) -> str:
    payload = f"{prev}|{e.session_id}|{e.timestamp_nano}|{e.tool}|{e.params_json}|{e.outcome}|{e.result_json}"
    return hashlib.sha256(payload.encode()).hexdigest()
```

- [ ] **Step 4: 实现 subscriber.py**

`cp/audit/subscriber.py`:
```python
import json

from cp.audit.ledger import Entry, Ledger
from cp.eventbus.bus import Bus, Event


def register_audit_subscriber(ledger: Ledger, bus: Bus) -> None:
    """让 ledger 订阅 bus 上的相关事件并写审计。审计逻辑的唯一集中点。"""

    def _on_event(e: Event) -> None:
        outcome = _outcome_for(e.type)
        if outcome == "":
            return  # 不审计的事件类型
        ledger.append(Entry(
            session_id=e.session_id,
            tool=e.tool,
            params_json=json.dumps(e.params, default=str),
            outcome=outcome,
            result_json=json.dumps(e.result, default=str),
        ))

    bus.subscribe(_on_event)


def _outcome_for(event_type: str) -> str:
    return {
        "tool.called": "allowed",
        "tool.denied": "denied",
        "tool.errored": "error",
        "session.started": "session_started",
        "session.ended": "session_ended",
        "quota.exceeded": "quota_exceeded",
    }.get(event_type, "")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest cp/tests/test_audit.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 提交**

```bash
git add cp/audit/ cp/tests/test_audit.py
git commit -m "feat(cp): hash-chain audit ledger + bus subscriber"
```

---

## Task 8: Session + Account

**Files:**
- Create: `cp/session/__init__.py`
- Create: `cp/session/session.py`
- Create: `cp/session/account.py`
- Test: `cp/tests/test_session_account.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_session_account.py`:
```python
import pytest

from cp.session.account import Account, ResourceQuota, Usage, QuotaExceeded


def test_charge_under_limit_succeeds():
    a = Account(ResourceQuota(max_steps=3, max_tokens=100))
    a.charge(Usage(steps=1, tokens=10))
    a.charge(Usage(steps=1, tokens=10))
    assert a.used().steps == 2


def test_charge_over_steps_rejected():
    a = Account(ResourceQuota(max_steps=2, max_tokens=100))
    a.charge(Usage(steps=1))
    a.charge(Usage(steps=1))
    with pytest.raises(QuotaExceeded):
        a.charge(Usage(steps=1))


def test_charge_over_tokens_rejected():
    a = Account(ResourceQuota(max_steps=10, max_tokens=50))
    with pytest.raises(QuotaExceeded):
        a.charge(Usage(steps=1, tokens=60))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_session_account.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 account.py**

`cp/session/__init__.py`: (空文件)

`cp/session/account.py`:
```python
import threading
from dataclasses import dataclass


class QuotaExceeded(Exception):
    pass


@dataclass
class ResourceQuota:
    max_steps: int = 0
    max_tokens: int = 0


@dataclass
class Usage:
    steps: int = 0
    tokens: int = 0


class Account:
    """累计资源消耗,超限拒绝。线程安全。"""

    def __init__(self, quota: ResourceQuota):
        self._mu = threading.Lock()
        self.quota = quota
        self._used = Usage()

    def charge(self, u: Usage) -> None:
        """扣减资源。任一项超限抛 QuotaExceeded(但已累加,调用方应终止)。"""
        with self._mu:
            self._used.steps += u.steps
            self._used.tokens += u.tokens
            if self.quota.max_steps > 0 and self._used.steps > self.quota.max_steps:
                raise QuotaExceeded()
            if self.quota.max_tokens > 0 and self._used.tokens > self.quota.max_tokens:
                raise QuotaExceeded()

    def used(self) -> Usage:
        with self._mu:
            return Usage(steps=self._used.steps, tokens=self._used.tokens)
```

- [ ] **Step 4: 实现 session.py**

`cp/session/session.py`:
```python
from dataclasses import dataclass

from cp.audit.ledger import Ledger
from cp.policy.gate import Gate
from cp.policy.policy import Policy
from cp.sanitize.sanitizer import Sanitizer
from cp.session.account import Account, ResourceQuota


@dataclass
class Session:
    """一个运行中 agent 的内核侧状态。Pipeline 不放这里(避免循环依赖)。"""
    id: str
    identity: str
    policy: Policy
    gate: Gate
    sanitizer: Sanitizer
    account: Account
    ledger: Ledger

    @classmethod
    def new(cls, sid: str, identity: str, pol: Policy, san: Sanitizer, ledger: Ledger) -> "Session":
        return cls(
            id=sid,
            identity=identity,
            policy=pol,
            gate=Gate(pol),
            sanitizer=san,
            account=Account(ResourceQuota(max_steps=pol.max_steps, max_tokens=pol.max_tokens)),
            ledger=ledger,
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest cp/tests/test_session_account.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 提交**

```bash
git add cp/session/ cp/tests/test_session_account.py
git commit -m "feat(cp): session + account with quota enforcement"
```

---

## Task 9: Auth + PolicyGuard

**Files:**
- Create: `cp/auth/__init__.py`
- Create: `cp/auth/auth.py`
- Create: `cp/auth/policy_guard.py`
- Test: `cp/tests/test_auth.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_auth.py`:
```python
import os
import tempfile

from cp.auth.auth import LocalAuthenticator
from cp.auth.policy_guard import is_trusted_policy


def test_local_authenticator_returns_local_identity():
    ident = LocalAuthenticator().authenticate(None)
    assert ident.tenant == "default"
    assert ident.user == "local"


def test_trusted_policy_inside_dir_allowed():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        open(p, "w").close()
        assert is_trusted_policy(p, d)


def test_trusted_policy_outside_dir_rejected():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        p = os.path.join(d2, "evil.yaml")
        open(p, "w").close()
        assert not is_trusted_policy(p, d1)


def test_trusted_policy_traversal_rejected():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "../../../etc/passwd")
        assert not is_trusted_policy(p, d)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 auth.py**

`cp/auth/__init__.py`: (空文件)

`cp/auth/auth.py`:
```python
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Identity:
    tenant: str = "default"
    user: str = "local"


class Authenticator(Protocol):
    """验证调用方身份。MVP 用 LocalAuthenticator;未来加 mTLS/API key 是新实现。"""

    def authenticate(self, ctx: Any) -> Identity: ...


class LocalAuthenticator:
    """MVP 实现:不验证,返回固定 "local" 身份。
    前提:本机只有可信进程能连 socket(由 socket 权限保证)。"""

    def authenticate(self, ctx: Any) -> Identity:
        return Identity(tenant="default", user="local")
```

- [ ] **Step 4: 实现 policy_guard.py**

`cp/auth/policy_guard.py`:
```python
import os


def is_trusted_policy(policy_path: str, trusted_dir: str) -> bool:
    """检查 Policy 路径是否在某个受信目录内。防止加载全权限恶意 Policy。"""
    try:
        abs_p = os.path.abspath(policy_path)
        abs_dir = os.path.abspath(trusted_dir)
        rel = os.path.relpath(abs_p, abs_dir)
    except ValueError:
        return False
    # rel 不能以 ".." 开头(逃出受信目录)
    if rel == ".." or rel.startswith(".." + os.sep) or rel.startswith("../"):
        return False
    return True
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest cp/tests/test_auth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 提交**

```bash
git add cp/auth/ cp/tests/test_auth.py
git commit -m "feat(cp): authenticator + trusted-policy path guard"
```

---

## Task 10: Scheduler

**Files:**
- Create: `cp/scheduler/__init__.py`
- Create: `cp/scheduler/scheduler.py`
- Test: `cp/tests/test_scheduler.py`

**注:** Week 1 用 threading(同步语义,对应 Go);Week 2 改 asyncio。

- [ ] **Step 1: 写失败测试**

`cp/tests/test_scheduler.py`:
```python
import threading
import time

from cp.scheduler.scheduler import Scheduler


def test_acquire_release_allows_reuse():
    s = Scheduler(2)
    r1 = s.acquire()
    r2 = s.acquire()
    r1()
    r2()
    r3 = s.acquire()  # 应立即拿到
    r3()


def test_concurrency_limit_enforced():
    s = Scheduler(1)
    held = threading.Event()
    release = threading.Event()
    results = []

    def holder():
        r = s.acquire()
        held.set()
        release.wait()
        r()

    t = threading.Thread(target=holder)
    t.start()
    held.wait()
    # 此时槽被占,acquire 应阻塞
    got = threading.Event()

    def waiter():
        r = s.acquire()
        got.set()
        r()

    tw = threading.Thread(target=waiter)
    tw.start()
    time.sleep(0.05)
    assert not got.is_set()  # 仍阻塞
    release.set()
    t.join()
    tw.join()
    assert got.is_set()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`cp/scheduler/__init__.py`: (空文件)

`cp/scheduler/scheduler.py`:
```python
import threading


class Scheduler:
    """用信号量限制并发 agent 数。FIFO 公平(threading.Semaphore)。
    Week 1 同步实现;Week 2 改 asyncio.Semaphore + 多副本。"""

    def __init__(self, max_concurrent: int):
        self._sem = threading.Semaphore(max_concurrent)

    def acquire(self):
        """占一个并发槽。返回 release 函数释放槽。"""
        self._sem.acquire()
        return self._sem.release
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_scheduler.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/scheduler/ cp/tests/test_scheduler.py
git commit -m "feat(cp): semaphore scheduler (sync, async in week 2)"
```

---

## Task 11: Pipeline 6 步管道

**Files:**
- Create: `cp/pipeline/__init__.py`
- Create: `cp/pipeline/pipeline.py`
- Test: `cp/tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

`cp/tests/test_pipeline.py`:
```python
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.policy.policy import Policy, Rule
from cp.sanitize.sanitizer import Sanitizer, FieldRule
from cp.session.account import ResourceQuota
from cp.session.session import Session
from cp.audit.ledger import Ledger
from cp.tools.tool import Registry, ToolResult
from cp.resource import Resource

import json
import tempfile


class StubTool:
    def __init__(self, name, data=None, raise_err=False):
        self._name = name
        self._data = data or {}
        self._raise = raise_err

    def name(self):
        return self._name

    def schema(self):
        return '{"name":"%s"}' % self._name

    def permission_key(self, params):
        return Resource(type="path", id=params.get("path", ""))

    def execute(self, ctx, params):
        if self._raise:
            raise RuntimeError("boom")
        return ToolResult(data=dict(self._data))


def _session(tmpdir, rules, san_rules=None):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    san = Sanitizer.new_from_rules(san_rules or [])
    ledger = Ledger(tmpdir + "/a.log")
    return Session.new("s1", "local", pol, san, ledger)


def test_pipeline_allows_and_returns_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "hello"}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "fs_read", {"path": "examples/x"})
        assert resp.allowed
        assert resp.result["content"] == "hello"


def test_pipeline_denies_unknown_tool():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        pipe = Pipeline(Registry(), bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "shell_exec", {"path": "rm -rf /"})
        assert not resp.allowed


def test_pipeline_denies_unauthorized_path():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "fs_read", {"path": "/etc/shadow"})
        assert not resp.allowed


def test_pipeline_sanitizes_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"phone": "13812341234", "amount": 120}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])],
                        [FieldRule("phone", "mask", 3, 4)])
        resp = pipe.call(sess, "fs_read", {"path": "examples/x"})
        assert resp.result["phone"] == "138********1234"
        assert resp.result["amount"] == 120


def test_pipeline_publishes_tool_called_event():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "y"}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        seen = []
        bus.subscribe(lambda e: seen.append(e))
        pipe.call(sess, "fs_read", {"path": "examples/x"})
        types = [e.type for e in seen]
        assert "tool.called" in types


def test_pipeline_quota_exceeded_terminates():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        pipe = Pipeline(reg, bus)
        pol = Policy(permissions=[Rule("path", "examples/**", ["fs_read"])],
                     max_steps=1, max_tokens=100000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        pipe.call(sess, "fs_read", {"path": "examples/x"})  # 用掉唯一一步
        resp = pipe.call(sess, "fs_read", {"path": "examples/y"})
        assert resp.errored
        assert "quota" in resp.message
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest cp/tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`cp/pipeline/__init__.py`: (空文件)

`cp/pipeline/pipeline.py`:
```python
from dataclasses import dataclass, field
from typing import Any, Dict

from cp.eventbus.bus import Bus, Event, FieldSanitization
from cp.session.account import QuotaExceeded, Usage
from cp.session.session import Session
from cp.tools.tool import Registry


@dataclass
class PipelineResponse:
    allowed: bool = False
    errored: bool = False
    message: str = ""
    result: Dict[str, Any] = field(default_factory=dict)


class Pipeline:
    """6 步统一管道。控制面核心只调它,不认识任何具体工具。

    步骤:查找 → 提取权限 → 权限检查 → 资源扣减 → 执行 → 脱敏 → 审计(事件)。
    """

    def __init__(self, registry: Registry, bus: Bus):
        self.registry = registry
        self.bus = bus

    def call(self, sess: Session, tool_name: str, params: Dict[str, Any]) -> PipelineResponse:
        # 步骤 1:查找工具。未知工具 = 拒绝(不泄露工具清单细节)。
        tool, ok = self.registry.get(tool_name)
        if not ok:
            self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 2:提取权限资源(工具自描述)。
        res = tool.permission_key(params)

        # 步骤 3:权限检查。不通过 → 拒绝 + 审计(拒绝原因不回传,防泄露)。
        if not sess.gate.allowed(tool_name, res):
            self.bus.publish(Event(type="tool.denied", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(allowed=False, message="permission denied")

        # 步骤 3.5:资源扣减。超限 → 硬终止 + quota.exceeded 事件。
        try:
            sess.account.charge(Usage(steps=1))
        except QuotaExceeded:
            self.bus.publish(Event(type="quota.exceeded", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="quota exceeded")

        # 步骤 4:执行工具。
        try:
            result = tool.execute(None, params)
        except Exception:
            self.bus.publish(Event(type="tool.errored", session_id=sess.id, tool=tool_name, params=params))
            return PipelineResponse(errored=True, message="tool error")

        # 步骤 5:脱敏(第一道安全防线,独立于工具)。保留摘要进事件。
        san_summary = []
        if sess.sanitizer is not None:
            sr = sess.sanitizer.sanitize(result.data)
            result.data = sr.data
            san_summary = [FieldSanitization(field=f.field, strategy=f.strategy) for f in sr.summary]

        # 步骤 6:审计(通过事件触发 AuditSubscriber,不散落)。含脱敏摘要。
        self.bus.publish(Event(
            type="tool.called", session_id=sess.id, tool=tool_name,
            params=params, result=result.data, sanitize=san_summary,
        ))

        return PipelineResponse(allowed=True, result=result.data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest cp/tests/test_pipeline.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 提交**

```bash
git add cp/pipeline/ cp/tests/test_pipeline.py
git commit -m "feat(cp): 6-step pipeline (lookup→perm→quota→exec→sanitize→audit)"
```

---

## Task 12: 对抗测试移植(硬里程碑)

**Files:**
- Create: `cp/tests/adversarial/__init__.py`
- Create: `cp/tests/adversarial/test_adversarial.py`

**这是 Week 1 的关键里程碑:8 个红队用例在 Python 下全部通过,证明安全逻辑零退化。**

- [ ] **Step 1: 写对抗测试(忠实移植 Go 版)**

`cp/tests/adversarial/__init__.py`: (空文件)

`cp/tests/adversarial/test_adversarial.py`:
```python
"""对抗安全测试——护城河证明。忠实移植自 kernel/test/adversarial/adversarial_test.go。
8 个用例全部通过 = 安全逻辑从 Go 迁到 Python 零退化。"""
import os

from cp.policy.gate import Gate
from cp.policy.policy import load_from_file
from cp.resource import Resource
from cp.sanitize.sanitizer import load_from_file as load_san


def _load_real_gate() -> Gate:
    """加载 examples/policies/data_analyst.yaml,测随产品发布的真实策略。"""
    return Gate(load_from_file("examples/policies/data_analyst.yaml"))


def test_adversarial_read_etc_shadow():
    assert not _load_real_gate().allowed("fs_read", Resource("path", "/etc/shadow"))


def test_adversarial_read_abs_windows_secret():
    assert not _load_real_gate().allowed("fs_read",
                                         Resource("path", "C:/Windows/System32/config/SAM"))


def test_adversarial_traversal_escape():
    g = _load_real_gate()
    attacks = [
        "examples/workspace/../../../../etc/passwd",
        "examples/workspace/../../../.ssh/id_rsa",
        "examples/workspace/out/../../../secret",
    ]
    for a in attacks:
        assert not g.allowed("fs_read", Resource("path", a)), a


def test_adversarial_write_outside_out_dir():
    g = _load_real_gate()
    # data_analyst 只能写 examples/workspace/out/**
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/sales.csv"))
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/evil.txt"))


def test_adversarial_unknown_tool():
    assert not _load_real_gate().allowed("shell_exec", Resource("path", "rm -rf /"))


def test_adversarial_unknown_resource_type():
    assert not _load_real_gate().allowed("db_query", Resource("db_table", "orders"))


def test_adversarial_network_disabled():
    assert not _load_real_gate().allowed("net_fetch", Resource("http_url", "https://evil.com/exfil"))


def test_adversarial_sanitization_masks_pii():
    s = load_san("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({
        "phone": "13812341234",
        "customer_id": "C001",
        "remark": "secret",
        "amount": 120,
    })
    assert out["phone"] != "13812341234"
    assert out["customer_id"] != "C001"
    assert "remark" not in out
    assert out["amount"] == 120
```

- [ ] **Step 2: 跑对抗测试**

Run: `pytest cp/tests/adversarial/test_adversarial.py -v`
Expected: **PASS (8 passed)**

如果有用例失败:**不要改测试**。失败说明移植有退化,回头修对应模块(通常是 gate 的 glob 匹配或 path 清洗)。这是 TDD 的红线——测试是黄金标准。

- [ ] **Step 3: 提交**

```bash
git add cp/tests/adversarial/
git commit -m "test(cp): port 8 adversarial cases — security moat zero-regression"
```

---

## Task 13: 架构测试移植(开闭原则)

**Files:**
- Create: `cp/tests/architecture/__init__.py`
- Create: `cp/tests/architecture/test_open_closed.py`

- [ ] **Step 1: 写架构测试**

`cp/tests/architecture/__init__.py`: (空文件)

`cp/tests/architecture/test_open_closed.py`:
```python
"""架构验证:开闭原则。加新工具只需实现 Tool 接口 + 注册,核心(Pipeline/Gate)零改。
移植自 kernel/test/architecture/open_closed_test.go。"""
import json
import tempfile

from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.policy.policy import Policy, Rule
from cp.resource import Resource
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session
from cp.tools.tool import Registry, ToolResult


class DBQueryStub:
    """一个全新的、和 fs 完全无关的工具。证明加新工具核心零改。"""

    def name(self) -> str:
        return "db_query"

    def schema(self) -> str:
        return '{"name":"db_query","description":"stub"}'

    def permission_key(self, params):
        return Resource(type="db_table", id=params.get("table", ""))

    def execute(self, ctx, params):
        return ToolResult(data={"rows": [{"id": 1}]})


def _session(rules):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    with tempfile.TemporaryDirectory() as d:
        return Session.new("arch-test", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))


def test_open_closed_adding_new_tool_requires_zero_kernel_changes():
    sess = _session([Rule("db_table", "sales.orders", ["db_query"])])
    reg = Registry()
    reg.register(DBQueryStub())  # 注册新工具——唯一新增的代码
    bus = InProcess()
    pipe = Pipeline(reg, bus)

    # 允许查询 sales.orders(Gate 用 db_table 规则匹配,无需认识 db_query 工具)
    resp = pipe.call(sess, "db_query", {"table": "sales.orders"})
    assert resp.allowed
    assert len(resp.result["rows"]) == 1

    # 拒绝查询未授权的表(finance.salaries 不匹配 sales.orders 模式)
    resp = pipe.call(sess, "db_query", {"table": "finance.salaries"})
    assert not resp.allowed


def test_open_closed_new_tool_publishes_events():
    sess = _session([Rule("db_table", "sales.orders", ["db_query"])])
    reg = Registry()
    reg.register(DBQueryStub())
    bus = InProcess()
    pipe = Pipeline(reg, bus)

    saw = []
    bus.subscribe(lambda e: saw.append(e))
    pipe.call(sess, "db_query", {"table": "sales.orders"})
    assert any(e.type == "tool.called" and e.tool == "db_query" for e in saw)
```

- [ ] **Step 2: 跑架构测试**

Run: `pytest cp/tests/architecture/test_open_closed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 3: 全量回归**

Run: `pytest cp/ -v`
Expected: 全部通过(约 8+7+5+5+3+5+3+4+2+6+8+2 = 58 个测试)

- [ ] **Step 4: 提交**

```bash
git add cp/tests/architecture/
git commit -m "test(cp): port open-closed architecture test"
```

---

## Week 1 完成判据(Definition of Done)

全部满足才进入 Week 2:

- [ ] `pytest cp/ -v` 全绿(约 58 个测试)
- [ ] 8 个对抗用例全部通过(安全零退化)
- [ ] 开闭原则测试通过(加 db_query 工具零改核心)
- [ ] 真实策略 `examples/policies/data_analyst.yaml` + 真实脱敏 `examples/sanitization/pii_rules.yaml` 被测试加载并验证
- [ ] hash 链审计:append + verify + 篡改检测均通过
- [ ] 源码无 TODO/FIXME(与 Go 基线一致)

---

## 自检(Self-Review)

**1. 规格覆盖:** V2 Week 1 目标 = 安全内核忠实移植 + 对抗零退化。13 个任务覆盖了 Go kernel 的全部 12 个 internal 模块(resource/policy/gate/sanitize/sandbox/tools/eventbus/audit/session/account/auth/scheduler)+ pipeline + 2 个测试套件(adversarial/architecture)。Gateway 的 runmgr/api/ws/kclient 不在 Week 1——它们在 Week 2-4 的拓扑改造中重写,因为 V2 拓扑下它们的形态完全不同。✅

**2. 占位符扫描:** 无 TBD/TODO/"later"。所有代码步骤含完整可运行代码。✅

**3. 类型一致性:** `Resource(type, id)`、`Gate.allowed(action, res)`、`Sanitizer.sanitize/sanitize_data`、`Tool.name/schema/permission_key/execute`、`Registry.register/get`、`Pipeline.call(sess, tool_name, params)`、`Session.new(...)`、`Account.charge/used`、`Ledger.append/read_all`、`verify_chain`——在所有任务中命名一致。`FieldSanitization(field, strategy)` 在 eventbus 与 sanitize 两处独立定义(与 Go 一致,避免循环依赖)。✅

**4. 已知风险(执行时注意):**
- `os.path.realpath` 与 Go `filepath.EvalSymlinks` 在 Windows 符号链接/junction 上行为可能有细微差异;Task 2 的单测覆盖穿越与绝对路径,但符号链接逃逸的实测需要在有符号链接的环境补一个测试(执行时如遇差异,以对抗测试为准修 `resolve`)。
- glob `**` 匹配器是自实现的,非标准库;Task 3 的 8 个 gate 测试 + Task 12 的对抗测试共同验证其正确性。若未来需更严格语义,可换 `pathlib.PurePath.full_match`(Python 3.13+)。
- Week 1 全同步(threading);Week 2 改 asyncio 时,`threading.Lock`→`asyncio.Lock`、`threading.Semaphore`→`asyncio.Semaphore`、同步 `Ledger.append`→需放线程池或改 async。这些在 Week 2 计划详述。
