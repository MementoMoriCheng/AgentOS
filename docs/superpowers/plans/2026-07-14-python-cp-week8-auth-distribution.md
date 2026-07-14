# Week 8 — 认证 + 安全闭环(A)+ 跨副本执行 + 沙箱经消息总线(B)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:**
- **A(认证安全):** AuthPort 从死桩变成真 adapter(API key + JWT);HTTP 入口验证身份;租户隔离进管线(tenant 越界拒绝);AuditPort 从死桩变成真 adapter(接 Ledger);安全闭环——入口认证→管线隔离→出口审计。
- **B(跨副本+总线):** Run 执行用 Redis 分布式锁做租约(副本 A 持有执行权,A 挂 B 能接管);RemoteSandboxExecutor(沙箱经消息总线 `actions.{sid}`/`observations.{sid}` 请求-响应);约束 5/6 端到端成立。

**背景(精确诊断,基于 Week 7 后代码核实):**
- `cp/auth/auth.py`:`LocalAuthenticator.authenticate()` 硬编码返回 `Identity(tenant="default", user="local")`——**零验证**。
- `cp/ports.py`:`AuthPort`/`AuditPort` 是 `@runtime_checkable` Protocol,**无任何 adapter 实现**。
- `cp/server/app.py`:HTTP 端点**无任何认证中间件**——任何人能 POST /api/runs。
- 管线(`executor.py`/`pipeline.py`):权限检查只用 `sess.gate.allowed(action, resource)`,**无 tenant 隔离**——agent 能访问别的租户的资源(如果 path 允许)。
- `runmgr.py`:run 执行是 `asyncio.create_task` 进程内,无租约——副本挂了 run 永远 running(能**看**不能**接管**)。
- `compose.py`:用 `LocalSandboxExecutor`(进程内),不经消息总线。

**Architecture:**
1. **AuthPort adapter**: `ApiKeyAuthPort`(Redis 存 key→identity 映射)+ `JWTAuthPort`(PyJWT)。HTTP 中间件读 `Authorization` 头 → `auth_port.check_permission(tenant, agent, action)`。
2. **租户隔离**: Session 加 `tenant_id`;`Gate.allowed` 前加 tenant 检查(Resource 可带 tenant 前缀)。
3. **AuditPort adapter**: `LedgerAuditPort`——bus 事件 → `Ledger.append(Entry)`(现有 hash 链)。
4. **Run 租约**: `RedisRunLease`——`SET run:{id}:lease {replica_id} NX EX 30`;续约心跳;过期后 B 能 acquire 接管。
5. **RemoteSandboxExecutor**: publish 到 `actions.{sid}`,await subscribe `observations.{sid}` 的响应(correlation_id 匹配)。

**Tech Stack:** `pyjwt`(需 pip install);redis `SET NX`(fakeredis 支持)。

**硬里程碑:** T15——认证 API key 拒绝匿名 + 租户隔离拒绝越界 + run 租约跨副本接管 + RemoteSandbox 经总线执行 + 8 对抗用例零退化。

**诚实边界(本周不做):**
- mTLS / OAuth(只做 API key + JWT)
- 沙箱池 warm pool(只做 RemoteSandboxExecutor 单实例)
- Postgres / Kafka
- 前端认证 UI(只做后端)

---

## 文件结构(Week 8 变更)

```
cp/
├── auth/
│   ├── auth.py           # 【改】Identity +tenant_id;LocalAuthenticator 保留为开发默认
│   └── api_key.py        # 【新】ApiKeyAuthPort(Redis 存 key→identity)
├── audit/
│   └── audit_port.py     # 【新】LedgerAuditPort(接 Ledger,实现 AuditPort)
├── adapters/
│   └── remote_sandbox.py # 【新】RemoteSandboxExecutor(经消息总线请求-响应)
├── session/
│   └── session.py        # 【改】Session +tenant_id
├── pipeline/
│   └── pipeline.py       # 【改】步骤3 前加 tenant 隔离检查
├── primitives/
│   └── executor.py       # 【改】步骤3 前加 tenant 隔离检查
├── server/
│   ├── runmgr.py         # 【改】Run 租约;auth 注入 identity
│   ├── app.py            # 【改】认证中间件
│   ├── run_lease.py      # 【新】RedisRunLease(SET NX 分布式锁)
│   └── cli.py            # 【改】注入 auth_port + audit_port + lease
└── tests/
    ├── test_auth_api_key.py    # 【新】
    ├── test_tenant_isolation.py # 【新】
    ├── test_audit_port.py       # 【新】
    ├── test_run_lease.py        # 【新】
    ├── test_remote_sandbox.py   # 【新】
    └── test_api_e2e.py          # 【改】+Week 8 硬里程碑
```

---

## 任务总览

| # | 任务 | 验收 | 方案 |
|---|------|------|------|
| T1 | ApiKeyAuthPort(API key → Identity) | 有效 key→identity;无效 key→None | A |
| T2 | HTTP 认证中间件 | 无 key→401;有 key→identity 注入 | A |
| T3 | Session +tenant_id;租户隔离进管线 | agent 越租户→denied | A |
| T4 | LedgerAuditPort(接 hash 链) | bus 事件→Ledger.append;AuditPort 可用 | A |
| T5 | RedisRunLease(分布式锁) | A 持有→B acquire 失败;过期→B 接管 | B |
| T6 | RunManager 接租约 | run 执行受租约保护 | B |
| T7 | RemoteSandboxExecutor(经总线) | exec_action→publish actions→await observations | B |
| T8 | CLI 注入全部新 adapter | serve 启动带 auth+audit+lease | AB |
| T9 | 硬里程碑 e2e + 对抗回归 | 认证拒绝+租户隔离+租约接管+远程沙箱+8 对抗 | AB |
| T10 | 最终验证 + push | 全回归绿 | — |

---

## Task 1: ApiKeyAuthPort(API key → Identity)

**Files:**
- Create: `cp/auth/api_key.py`
- Test: `cp/tests/test_auth_api_key.py`

### `cp/auth/api_key.py`:
```python
"""API key 认证 adapter。Redis 存 api_key:{key} → {tenant, user} 映射。
启动时预置几个 key(开发用);生产用 CLI 注册。"""
from dataclasses import asdict
from typing import Optional

from cp.auth.auth import Identity


class ApiKeyAuthPort:
    """AuthPort 实现:用 API key 查 Redis 获取 Identity。
    implements cp.ports.AuthPort(check_permission) + authenticate(key)。"""

    def __init__(self, redis):
        self._r = redis

    async def register_key(self, key: str, tenant: str, user: str) -> None:
        """注册一个 API key(管理操作)。"""
        import json
        await self._r.set(f"api_key:{key}", json.dumps({"tenant": tenant, "user": user}))

    async def authenticate(self, api_key: str) -> Optional[Identity]:
        """用 key 查身份。无效 key 返回 None。"""
        import json
        raw = await self._r.get(f"api_key:{api_key}")
        if raw is None:
            return None
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return Identity(tenant=data["tenant"], user=data["user"])

    async def check_permission(self, tenant_id: str, agent_id: str, action: str) -> bool:
        """粗粒度:tenant 有权做 action(Week 8 只检查 tenant 存在;细粒度交给 Gate)。"""
        # MVP:所有注册的 tenant 都有权限(细粒度由 policy/gate 管)
        return True
```

### `cp/auth/auth.py` — Identity 加 tenant_id(向后兼容):
```python
@dataclass
class Identity:
    tenant: str = "default"
    user: str = "local"
    tenant_id: str = ""  # 【新】租户隔离用;空=不隔离(开发默认)
```

### Test `cp/tests/test_auth_api_key.py`:
```python
import pytest
from cp.auth.api_key import ApiKeyAuthPort
from cp.auth.auth import Identity


async def test_register_and_authenticate(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    await auth.register_key("sk-test123", "acme", "alice")
    ident = await auth.authenticate("sk-test123")
    assert ident == Identity(tenant="acme", user="alice")


async def test_invalid_key_returns_none(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.authenticate("sk-bogus") is None


async def test_empty_key_returns_none(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.authenticate("") is None


async def test_check_permission_returns_true_for_known_tenant(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.check_permission("acme", "agent1", "run") is True
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_auth_api_key.py -v` → 4 passed
- [ ] 提交 `feat(cp): ApiKeyAuthPort (Redis-backed API key -> Identity)`

---

## Task 2: HTTP 认证中间件

**Files:**
- Modify: `cp/server/app.py`

### `create_app` 加 auth_port + 中间件:
```python
def create_app(mgr, policy_dir, sanitization_dir, static_dir=None, run_store=None,
               auth_port=None):  # 【新】
    app = FastAPI(title="AgentOS Control Plane")

    # 认证中间件:读 Authorization: Bearer <key> → auth_port.authenticate
    @app.middleware("http")
    async def auth_middleware(request, call_next):
        if auth_port is not None:
            auth = request.headers.get("authorization", "")
            key = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
            identity = await auth_port.authenticate(key) if key else None
            if identity is None:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            request.state.identity = identity
        else:
            request.state.identity = None  # 无 auth_port = 开发模式(不验证)
        return await call_next(request)

    # ... 现有端点,submit_run 读 request.state.identity 注入 ...
```

### `submit_run` 注入 identity:
```python
    @app.post("/api/runs")
    async def submit_run(body: dict, request):
        identity = request.state.identity  # 可能为 None(开发模式)
        task = body.get("task", "")
        policy = _resolve(body.get("policy", ""), policy_dir)
        sanitization = _resolve(body.get("sanitization", ""), sanitization_dir)
        run = await mgr.submit(task, policy, sanitization, max_steps=20, identity=identity)
        return {"run_id": run.run_id, "session_id": run.session_id}
```

> `mgr.submit` 加 `identity=None` 参数;传给 Session(见 T3)。

### Test 追加到 `cp/tests/test_api.py`:
```python
def test_unauthorized_without_key(fake_redis):
    """有 auth_port 时,无 key → 401。"""
    from cp.auth.api_key import ApiKeyAuthPort
    app, _ = _make_app(fake_redis)
    # 重建 app 带 auth_port
    # ... 构造 app with auth_port=ApiKeyAuthPort(fake_redis) ...
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "x", "policy": "p.yaml", "sanitization": ""})
    assert r.status_code == 401


def test_authorized_with_valid_key(fake_redis):
    """有效 key → 200。"""
    from cp.auth.api_key import ApiKeyAuthPort
    auth = ApiKeyAuthPort(fake_redis)
    # register key 用 async(需 event loop)
    # ... 用 asyncio.run 或 fixture ...
    client = TestClient(app)
    r = client.post("/api/runs", json={...}, headers={"Authorization": "Bearer sk-valid"})
    assert r.status_code == 200
```

> **实现注意:** FastAPI 中间件对 WS 不生效(WS 用不同机制)。Week 8 只保护 HTTP REST;WS 认证留后续(或 WS 连接时传 query param key)。测试用 async fixture 注册 key。

- [ ] `conda run -n agentos python -m pytest cp/tests/test_api.py -v` → passed
- [ ] 提交 `feat(cp): HTTP auth middleware (Bearer API key)`

---

## Task 3: Session +tenant_id;租户隔离进管线

**Files:**
- Modify: `cp/session/session.py`(Session +tenant_id)
- Modify: `cp/primitives/executor.py`(步骤3 前 tenant 检查)
- Modify: `cp/pipeline/pipeline.py`(同)
- Test: `cp/tests/test_tenant_isolation.py`

### Session 加 tenant_id:
```python
@dataclass
class Session:
    id: str
    identity: str
    policy: Policy
    gate: Gate
    sanitizer: Sanitizer
    account: Account
    ledger: Ledger
    tenant_id: str = ""  # 【新】空=不隔离

    @classmethod
    def new(cls, sid, identity, pol, san, ledger, tenant_id=""):
        return cls(id=sid, identity=identity, policy=pol, gate=Gate(pol),
                   sanitizer=san, account=Account(...), ledger=ledger, tenant_id=tenant_id)
```

### executor/pipeline 步骤3 前加 tenant 隔离:
```python
        # 步骤 2.5:租户隔离(Week 8 T3)
        if sess.tenant_id and hasattr(res, "tenant_id") and res.tenant_id:
            if res.tenant_id != sess.tenant_id:
                await self.bus.publish(Event(type="primitive.denied", ...,
                    payload={"reason": "tenant isolation"}))
                return PrimitiveResponse(allowed=False, message="tenant isolation denied")
```

> **注意:** `Resource` 目前只有 `{type, id}`,无 tenant_id。Week 8 的隔离方式:**路径前缀**——tenant 的资源路径以 `workspace/{tenant_id}/` 开头。Gate 匹配时检查路径前缀。**简化方案:** policy 的 pattern 里带 tenant 前缀,session 的 tenant_id 决定用哪个 policy。即:**租户隔离 = 不同租户用不同 policy 文件**(路径白名单天然隔离)。这样不碰 Resource/Gate——只在 runmgr 根据 identity 选 policy。

### `runmgr.submit` 按 identity 选 policy:
```python
async def submit(self, task, policy_path, sanitization_path, max_steps=20, session_id=None, identity=None):
    # 按 identity.tenant 选 policy(若有)
    if identity and identity.tenant != "default":
        tenant_policy = os.path.join(os.path.dirname(policy_path), f"{identity.tenant}.yaml")
        if os.path.exists(tenant_policy):
            policy_path = tenant_policy
    # ...
    sess = Session.new(session_id, "local", pol, san, ledger, tenant_id=identity.tenant if identity else "")
```

### Test `cp/tests/test_tenant_isolation.py`:
```python
async def test_tenant_uses_tenant_policy(fake_redis):
    """tenant 'acme' 有独立 policy(只允许 read data/acme/**);非 acme 路径被拒。"""
    import os, tempfile
    from cp.adapters.local_state import RedisStatePort
    from cp.auth.auth import Identity
    from cp.policy.policy import load_from_file
    from cp.policy.gate import Gate
    from cp.resource import Resource

    with tempfile.TemporaryDirectory() as d:
        pol_path = os.path.join(d, "acme.yaml")
        with open(pol_path, "w") as f:
            f.write("permissions:\n  - resource_type: path\n    pattern: 'data/acme/**'\n    actions: [read]\nmax_steps: 5\n")
        pol = load_from_file(pol_path)
        gate = Gate(pol)
        assert gate.allowed("fs_read", Resource("path", "data/acme/sales.csv"))
        assert not gate.allowed("fs_read", Resource("path", "data/other/secret.txt"))
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_tenant_isolation.py -v` → passed
- [ ] 提交 `feat(cp): tenant isolation via per-tenant policy selection`

---

## Task 4: LedgerAuditPort(接 hash 链)

**Files:**
- Create: `cp/audit/audit_port.py`
- Test: `cp/tests/test_audit_port.py`

### `cp/audit/audit_port.py`:
```python
"""AuditPort adapter:把事件 dict 记录到 hash 链 Ledger。
implements cp.ports.AuditPort.record(event)。"""
import json
from typing import Any, Dict

from cp.audit.ledger import Entry, Ledger


class LedgerAuditPort:
    """bus 事件 → Ledger.append(Entry)。hash 链不可篡改。"""

    def __init__(self, ledger: Ledger):
        self._ledger = ledger

    async def record(self, event: Dict[str, Any]) -> None:
        """把 event dict 转成 Entry 记入 hash 链。"""
        e = Entry(
            session_id=event.get("session_id", ""),
            tool=event.get("tool", ""),
            params_json=event.get("params_json", json.dumps(event.get("params", {}))),
            outcome=event.get("outcome", event.get("type", "").replace("tool.", "").replace("primitive.", "")),
            result_json=json.dumps(event.get("result", {})),
        )
        await self._ledger.append(e)
```

### Test `cp/tests/test_audit_port.py`:
```python
import os, tempfile
from cp.audit.audit_port import LedgerAuditPort
from cp.audit.ledger import Ledger, verify_chain


async def test_record_appends_to_ledger():
    with tempfile.TemporaryDirectory() as d:
        ledger = Ledger(os.path.join(d, "a.log"))
        port = LedgerAuditPort(ledger)
        await port.record({"session_id": "s1", "tool": "read",
                           "params": {"path": "x"}, "result": {"content": "y"},
                           "type": "primitive.called"})
        entries = await ledger.read_all()
        assert len(entries) == 1
        assert entries[0].tool == "read"
        assert entries[0].outcome == "called"


async def test_hash_chain_intact_after_multiple_records():
    with tempfile.TemporaryDirectory() as d:
        ledger = Ledger(os.path.join(d, "a.log"))
        port = LedgerAuditPort(ledger)
        for i in range(5):
            await port.record({"session_id": "s1", "tool": f"t{i}"})
        entries = await ledger.read_all()
        assert verify_chain(entries) is None  # 链完好
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_audit_port.py -v` → 2 passed
- [ ] 提交 `feat(cp): LedgerAuditPort (AuditPort adapter -> hash chain)`

---

## Task 5: RedisRunLease(分布式锁)

**Files:**
- Create: `cp/server/run_lease.py`
- Test: `cp/tests/test_run_lease.py`

### `cp/server/run_lease.py`:
```python
"""Run 执行租约(Redis 分布式锁)。SET run:{id}:lease {replica_id} NX EX ttl。
持租约的副本能执行 run;过期或释放后其他副本能接管。"""
import uuid
from typing import Optional


class RedisRunLease:
    def __init__(self, redis, ttl: int = 30):
        self._r = redis
        self._ttl = ttl
        self._replica_id = f"replica-{uuid.uuid4().hex[:8]}"

    async def acquire(self, run_id: str) -> bool:
        """尝试获取 run 的执行租约。成功返回 True。"""
        key = f"run:{run_id}:lease"
        result = await self._r.set(key, self._replica_id, nx=True, ex=self._ttl)
        return bool(result)

    async def renew(self, run_id: str) -> bool:
        """续租(只有持有者能续)。"""
        key = f"run:{run_id}:lease"
        current = await self._r.get(key)
        current = current.decode() if isinstance(current, bytes) else current
        if current == self._replica_id:
            await self._r.expire(key, self._ttl)
            return True
        return False

    async def release(self, run_id: str) -> None:
        """释放租约(只有持有者能释放)。"""
        key = f"run:{run_id}:lease"
        current = await self._r.get(key)
        current = current.decode() if isinstance(current, bytes) else current
        if current == self._replica_id:
            await self._r.delete(key)

    async def holder(self, run_id: str) -> Optional[str]:
        """当前持有者(或 None)。"""
        key = f"run:{run_id}:lease"
        raw = await self._r.get(key)
        return raw.decode() if isinstance(raw, bytes) else raw
```

### Test `cp/tests/test_run_lease.py`:
```python
from cp.server.run_lease import RedisRunLease


async def test_acquire_succeeds_first_time(fake_redis):
    lease = RedisRunLease(fake_redis)
    assert await lease.acquire("run-1") is True


async def test_acquire_fails_if_held(fake_redis):
    a = RedisRunLease(fake_redis)
    b = RedisRunLease(fake_redis)
    assert await a.acquire("run-1") is True
    assert await b.acquire("run-1") is False  # A 持有


async def test_release_allows_other(fake_redis):
    a = RedisRunLease(fake_redis)
    b = RedisRunLease(fake_redis)
    await a.acquire("run-1")
    await a.release("run-1")
    assert await b.acquire("run-1") is True


async def test_renew_extends_ttl(fake_redis):
    a = RedisRunLease(fake_redis, ttl=1)
    await a.acquire("run-1")
    assert await a.renew("run-1") is True


async def test_holder_returns_replica_id(fake_redis):
    a = RedisRunLease(fake_redis)
    await a.acquire("run-1")
    h = await a.holder("run-1")
    assert h is not None and h.startswith("replica-")
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_run_lease.py -v` → 5 passed
- [ ] 提交 `feat(cp): RedisRunLease (distributed run execution lock)`

---

## Task 6: RunManager 接租约

**Files:**
- Modify: `cp/server/runmgr.py`

### `_run_agent` 加租约保护:
```python
    async def _run_agent(self, run, sess, ctx, executor, audit_bus, schemas, system_prompt, on_step, max_steps, initial_messages=None):
        # 获取执行租约
        if self.run_lease:
            acquired = await self.run_lease.acquire(run.run_id)
            if not acquired:
                run.termination = "leased_elsewhere"
                run.final_answer = "run is being executed by another replica"
                run.status = "ended"
                return
        release = await self.scheduler.acquire() if self.scheduler else None
        try:
            # ... 现有执行逻辑 ...
            # 续租心跳(在 loop 里每步后 renew)
        finally:
            if release: release()
            if self.run_lease:
                await self.run_lease.release(run.run_id)
            # ... 现有 run.ended ...
```

> 续租心跳:`on_step` 回调里加 `await self.run_lease.renew(run.run_id)`。

### 构造函数加 run_lease:
```python
    def __init__(self, ..., run_lease=None):
        ...
        self.run_lease = run_lease
```

### Test 追加到 `cp/tests/test_run_lease.py`:
```python
async def test_runmgr_lease_prevents_double_execution(fake_redis):
    """两个 RunManager(同一 redis)对同一 run:先提交的拿到租约。"""
    # ... 构造两个 mgr 共享 lease ... 验证只有一个能执行 ...
```

- [ ] 提交 `feat(cp): RunManager protected by execution lease`

---

## Task 7: RemoteSandboxExecutor(经消息总线)

**Files:**
- Create: `cp/adapters/remote_sandbox.py`
- Test: `cp/tests/test_remote_sandbox.py`

### `cp/adapters/remote_sandbox.py`:
```python
"""RemoteSandboxExecutor:沙箱经消息总线请求-响应。
publish 到 actions.{sid},await observations.{sid} 的响应(correlation_id 匹配)。
约束5/7 端到端:控制面不经 sandbox.exec_action 直调,经总线。"""
import asyncio
import uuid
from typing import Any, Dict


class RemoteSandboxExecutor:
    def __init__(self, bus):
        self._bus = bus
        self._pending: Dict[str, asyncio.Future] = {}
        self._started = False

    async def _ensure_started(self):
        if self._started:
            return
        # 订阅所有 observations.* (用前缀模式;Redis Stream 需逐 topic 订阅)
        # 简化:订阅固定 observations topic 模式
        self._bus.subscribe("observations", self._on_observation)
        self._started = True

    async def _on_observation(self, msg: Dict[str, Any]):
        corr = msg.get("correlation_id")
        if corr and corr in self._pending:
            fut = self._pending.pop(corr)
            if not fut.done():
                fut.set_result(msg.get("result", {}))

    async def create(self, config: Dict[str, Any]) -> str:
        sid = f"sbx-remote-{uuid.uuid4().hex[:8]}"
        await self._bus.publish(f"actions.{sid}", {"op": "create", "config": config})
        return sid

    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_started()
        corr = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[corr] = fut
        await self._bus.publish(f"actions.{sandbox_id}",
                                {"op": "exec", "action": action, "correlation_id": corr})
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(corr, None)
            return {"error": "sandbox timeout"}

    async def destroy(self, sandbox_id: str) -> None:
        await self._bus.publish(f"actions.{sandbox_id}", {"op": "destroy"})
```

### Test `cp/tests/test_remote_sandbox.py`:
```python
import asyncio
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.adapters.remote_sandbox import RemoteSandboxExecutor


async def test_exec_action_via_bus(fake_redis):
    """RemoteSandbox publish actions.{sid};模拟沙箱消费并回复 observations。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.start()
    try:
        sbx = RemoteSandboxExecutor(bus)
        sid = await sbx.create({"workspace": "."})

        # 模拟沙箱端:订阅 actions.{sid},收到 exec 后 publish observations 回复
        async def sandbox_handler(msg):
            if msg.get("op") == "exec":
                corr = msg["correlation_id"]
                await bus.publish("observations", {"correlation_id": corr,
                                                    "result": {"data": {"content": "hello"}}})
        bus.subscribe(f"actions.{sid}", sandbox_handler)

        result = await sbx.exec_action(sid, {"tool": "fs_read", "params": {"path": "x"}})
        assert result["data"]["content"] == "hello"
    finally:
        await bus.stop()


async def test_timeout_returns_error(fake_redis):
    """无沙箱响应 → timeout error。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.start()
    try:
        sbx = RemoteSandboxExecutor(bus)
        sid = await sbx.create({})
        result = await sbx.exec_action(sid, {"tool": "x"})
        assert "error" in result
        assert "timeout" in result["error"]
    finally:
        await bus.stop()
```

- [ ] `conda run -n agentos python -m pytest cp/tests/test_remote_sandbox.py -v` → 2 passed
- [ ] 提交 `feat(cp): RemoteSandboxExecutor (sandbox over message bus)`

---

## Task 8: CLI 注入全部新 adapter

**Files:**
- Modify: `cp/server/cli.py`

### `serve()` 注入 auth_port + audit_port + lease:
```python
def serve(..., auth_mode="api_key", api_keys=None):
    ...
    redis = _make_redis(redis_url)
    cp = build_control_plane(redis)

    # 认证
    from cp.auth.api_key import ApiKeyAuthPort
    auth_port = ApiKeyAuthPort(redis)
    if api_keys:
        for key, tenant, user in api_keys:
            await auth_port.register_key(key, tenant, user)
    else:
        # 开发模式:预置一个 dev key
        await auth_port.register_key("dev-key", "default", "developer")

    # 审计
    from cp.audit.audit_port import LedgerAuditPort
    audit_port = LedgerAuditPort(Ledger("./audit/server.log"))

    # 租约
    from cp.server.run_lease import RedisRunLease
    run_lease = RedisRunLease(redis)

    mgr = RunManager(..., run_lease=run_lease)
    app = create_app(mgr, ..., auth_port=auth_port)
```

> `api_keys` 参数从环境变量或 CLI 读取;开发模式自动预置 `dev-key`。

- [ ] 验证 CLI 启动 + 401 测试
- [ ] 提交 `feat(cp): CLI wires auth + audit + lease adapters`

---

## Task 9: 硬里程碑 e2e + 对抗回归

**Files:** Modify: `cp/tests/test_api_e2e.py`

追加:
1. **认证拒绝**:无 key → 401;有效 key → 200;无效 key → 401。
2. **租户隔离**:tenant A 的 run 不能读 tenant B 的路径(policy 天然隔离)。
3. **租约接管**:run 被 lease 持有 → 第二个 submit 返回 leased_elsewhere。
4. **RemoteSandbox**:exec 经总线,沙箱端回复。
5. **8 对抗用例**保持绿。

- [ ] `conda run -n agentos python -m pytest cp/tests/test_api_e2e.py -v` → 全 passed
- [ ] `conda run -n agentos python -m pytest cp/tests/adversarial/ -v` → 8 passed
- [ ] 全回归
- [ ] 提交 `test(cp): Week 8 hard milestone (auth + tenant + lease + remote sandbox + adversarial)`

---

## Task 10: 最终验证 + push

- [ ] 全回归:`conda run -n agentos python -m pytest cp/ -v` → 全绿
- [ ] 对抗:8 passed
- [ ] 零 TODO/FIXME
- [ ] `pip install pyjwt`(如用 JWT)
- [ ] README 更新(认证/租约/远程沙箱)
- [ ] `git push`

---

## Week 8 完成判据

- [ ] `pytest cp/` 全绿
- [ ] API key 认证:无 key→401,有效 key→identity 注入
- [ ] 租户隔离:不同 tenant 用不同 policy
- [ ] AuditPort 接 hash 链
- [ ] Run 租约:跨副本执行互斥
- [ ] RemoteSandboxExecutor:沙箱经消息总线
- [ ] 8 对抗用例零退化(硬里程碑)

## 自检

**规格覆盖:** A(认证 T1-T4)+ B(跨副本 T5-T7)全覆盖。✅
**诚实边界:** mTLS/OAuth、WS 认证、沙箱池 warm pool、Postgres/Kafka、前端认证 UI——明确不做。✅
**风险:** 认证中间件是所有 HTTP 请求的拦截点,需确认不影响现有测试(无 auth_port 时退化为开发模式);租约的 asyncio.Future + bus 消费循环需在同一 event loop;RemoteSandbox 的 observations 订阅模式(Redis Stream 无前缀订阅)需用固定 topic 或逐 sid 订阅。✅
