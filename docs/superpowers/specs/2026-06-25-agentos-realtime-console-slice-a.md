# AgentOS 实时可观测控制台 · 切片 A 设计文档

- **日期**: 2026-06-25
- **状态**: ✅ **已实现**（2026-06-26 同步；原为草稿）。代码见 `gateway/`、`web-src/`，对应提交 `c15960b`→`1e0a54b`。
- **范围**: 综合控制台的第 1 个切片——**Web 网关 + 实时可观测仪表盘**
- **关系**: v2.3（`2026-06-24-agentos-mvp-design-v2.3.md`）把 Web UI 排除在阶段 0 之外（属阶段 2）。本文档将其中"实时可观测"这一能力提前，作为独立切片实现。对话交互界面（切片 B）、管理后台（切片 C）留后续 spec。

> **实现状态摘要（2026-06-26）**：本文档所有"目标"与"成功标准"均已达成。下方各节保留作设计记录；凡是实现时做了细化/取舍的地方，附「实现注记」标注。组件分解 §5 中各文件路径与实际代码一一对应。

---

## 0. 为什么是这个切片

用户反馈"项目缺前端显示界面"。综合控制台体量过大，强行一次做会烂尾。本切片聚焦**最能复用、最命中 demo 卖点**的部分：建起 HTTP/WebSocket 网关层 + 实时把 agent 干什么画出来。网关层一旦建成，B、C 复用同一套基础设施。

**不在本切片**：对话式提交（B）、policy/脱敏配置编辑（C）、持久化事件存储、多 run/多 session（MVP 1:1）、跨主机部署。

---

## 1. 目标与非目标

### 1.1 目标
1. 浏览器里**提交数据分析任务**，**实时**看到 agent 的 think/act/observe 每一步、工具调用、权限放行/拒绝、脱敏发生、审计落盘、run 收尾。
2. v2.3 的四个 demo 卖点在仪表盘**一眼可见**：能干活 / 被脱敏 / 被管住 / 能查。
3. **不削弱**现有安全模型：网关是 localhost 受信入口，安全权威仍在 Kernel。
4. Kernel 核心（Pipeline/Gate/EventBus）**零改动**，开闭原则保住。

### 1.2 非目标（明确排除）
- 网关认证（mTLS/API key）——MVP localhost-only，阶段 2 加。
- 事件持久化存储——MVP 网关内存事件环，进程重启即丢（审计仍在 Kernel ledger）。
- 多 run 并发编排——MVP 支持多个 run 但不做调度/优先级。
- 对话式多轮交互（切片 B）。
- policy/脱敏规则的可视化编辑（切片 C）；本切片只**只读列出**供下拉。

---

## 2. 架构（方案 2：独立网关）

```
┌──────────────┐  HTTP/WS   ┌──────────────┐  gRPC   ┌──────────────────────┐
│ ① 浏览器      │ ⇄ ⇄ ⇄ ⇄ ⇄ │ ② Web Gateway │ ⇄ ⇄ ⇄ │ ③ OS Kernel (已有)    │
│ React+Vite+TS│            │ (新·Go 单二进制)│        │ · 6 步 Pipeline      │
│ 仪表盘        │            │ · REST + WS    │        │ · EventBus(事件枢纽) │
│              │            │ · Run 编排     │        │ · Gate/Sanitizer/审计 │
└──────────────┘            │ · 事件扇出     │        │ +SubscribeEvents(新) │
                            │ · //go:embed   │        │ +EmitRuntimeEvent(新)│
                            │   前端静态文件  │        └──────────┬───────────┘
                            └───────┬────────┘                   │ gRPC
                                    │ exec 子进程                  │ CallTool/
                                    ↓                            │ EmitRuntimeEvent
                            ┌──────────────────┐                  │
                            │ ④ Runtime(已有)   │ ←─────────────────┘
                            │ · ReAct 循环      │
                            │ · DeepSeek LLM    │
                            │ +发推理事件(新)    │
                            └──────────────────┘
```

### 2.1 三条架构决定
1. **事件枢纽 = Kernel**：Runtime 的 think/observe 经 `EmitRuntimeEvent` 灌入 Kernel 的 EventBus，网关只订阅 Kernel 一个源，不合并两路流。代价：Kernel 多一个 unary RPC。
2. **Run 编排归网关**：提交任务时由网关 fork Runtime 子进程。Kernel 保持纯能力权威（不碰进程管理）。
3. **Session 生命周期归网关**：网关调 `StartSession` 拿 session_id，作为参数传给 fork 出的 Runtime。Runtime **不再自建 session**。网关天然拥有 run↔session 映射，能正确过滤事件。

### 2.2 为什么选独立网关而非"网关入 Kernel"
- 网关与 Kernel 职责彻底分离，可独立重启/演进。
- Kernel 仍是唯一事件枢纽 + 安全权威。
- 代价（已接受）：Kernel 必须新增 2 个跨进程 RPC（`SubscribeEvents`/`EmitRuntimeEvent`），4 个进程编排更复杂。

---

## 3. 事件模型

### 3.1 事件目录（两族，汇于 Kernel EventBus）

**Kernel 族**（已有 6 类，1 处增强 + 1 处补缺）：

| 事件 | 载荷 | 说明 |
|------|------|------|
| `session.started` | session_id, identity, policy_path | 已有 |
| `session.ended` | session_id, reason | **现状从未发布，本切片补上**（Server 在 run 结束/会话销毁时发） |
| `tool.called` | session_id, tool, params, result, **sanitize:[{field,strategy}]** | **新增 sanitize 摘要，无原始值** |
| `tool.denied` | session_id, tool, params | 已有 |
| `tool.errored` | session_id, tool, params | 已有 |
| `quota.exceeded` | session_id, tool, params | 已有 |

**Runtime 族**（全新，经 `EmitRuntimeEvent` 灌入）：

| 事件 | 载荷 |
|------|------|
| `run.started` | run_id, session_id, task, max_steps |
| `runtime.step` | run_id, session_id, step_index, thought, tool_calls:[{name,args}] |
| `run.ended` | run_id, session_id, termination: completed\|step_limit\|crashed\|timeout\|error, steps_used, final_answer |

### 3.2 两个设计决策
- **脱敏摘要不泄露原始值（决策 A）**：`tool.called` 的 `sanitize` 只列被脱敏字段名 + 策略（mask/hash/redact），**绝不**含原始值或脱敏后值。由 Sanitizer 在脱敏时产出摘要，Pipeline 组装事件时只引用。
- **step↔tool 时间序关联（决策 B，MVP 简化）**：一步可能调多个工具，按时间序匹配（一步内的 tool_calls 按顺序对应后续 tool.* 事件），不做显式 correlation id。单 Runtime 顺序调用下够用；并发多工具是已知简化。

### 3.3 推理过程安全可流
`runtime.step.thought` 流到浏览器。安全前提：**LLM 只见脱敏后结果**（Pipeline 第 5 步保证），故 thought 不含原始敏感数据。这是现有设计的副收益，非新风险。

### 3.4 一次 run 的事件时间线（仪表盘渲染依据）
```
run.started
runtime.step #0  thought:"先列文件"   tool_calls:[fs_list]
tool.called     fs_list  → sanitize:[]
runtime.step #1  thought:"读 csv"      tool_calls:[fs_read]
tool.called     fs_read  → sanitize:[{phone:mask},{id_card:mask}]
runtime.step #2  thought:"算总和写出"  tool_calls:[fs_write]
tool.called     fs_write → result
run.ended       termination:completed steps:3 final:"已写入 out/total.txt"
```

---

## 4. API 表面（网关 ②）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/runs` | body {task, policy, sanitization} → {run_id}。网关调 StartSession + fork Runtime |
| GET | `/api/runs` | → [{run_id, session_id, status, task, started_at}]（网关内存注册表） |
| GET | `/api/runs/:id` | → {run, events:[…]}（详情 + 事件回放，网关按 run 缓存） |
| GET | `/api/policies` | → [name]（只读，扫 examples/policies + policies 目录） |
| GET | `/api/sanitizations` | → [name]（只读，扫 examples/sanitization 目录） |
| WS | `/api/events?run_id=X` | 订阅；迟到连接先补播事件环历史，再续推实时 |
| GET | `/` 及静态资源 | 托管打包后的前端（//go:embed） |

**约定**：run_id 由网关分配（uuid），传给 Runtime 作 CLI 参数；1 run = 1 session（MVP 1:1）。

---

## 5. 组件分解

### 5.1 Kernel (Go) — 全加性，核心零改
- `proto/agentos.proto`：新增 `SubscribeEvents`（server-streaming）、`EmitRuntimeEvent`（unary）、`Event` message
- `internal/pb/`：protoc 重生成
- `internal/sanitize/`：`Sanitize()` 返回脱敏摘要 `Summary`（`[{field,strategy}]`），无原始值
- `internal/pipeline/`：`tool.called` 事件附 `sanitize` 摘要
- `internal/server/`：2 个新 RPC handler；**补发 `session.ended`**
- `internal/eventbus/`：**零改**（已够用）

### 5.2 Gateway (Go) — ★全新模块 `gateway/`
- `gateway/cmd/agentos-gateway/main.go`：`net/http` + WS，flags: kernel socket / http addr
- `gateway/internal/runmgr/`：run 注册表；fork Runtime 子进程；run↔session 映射；事件环
- `gateway/internal/api/`：REST handler（runs / policies / sanitizations）
- `gateway/internal/ws/`：WS hub；订阅 `SubscribeEvents` → 按 run 扇出 + 补播
- `gateway/internal/kclient/`：gRPC client → Kernel
- `gateway/web/dist/`：`//go:embed` 打包前端

### 5.3 Runtime (Python) — 加性改动
- `loop.py`：发 `run.started`/`runtime.step`/`run.ended`；**不再自建 session**（用传入的 session_id）
- `kernel_client.py`：新增 `emit_event(run_id, type, payload)`
- `cli.py`：接 `--run-id`/`--session-id`/`--task`（网关以子进程调用）；**约定退出码**（0=正常，非0=崩溃/报错）
- `llm/`、`rate_limit.py`、`tools.py`：零改

### 5.4 Frontend — ★全新 `web-src/`
- `App.tsx`：左 run 列表 + 右详情，两栏布局
- `views/`：`RunList` / `RunDetail`(时间线) / `RunSubmit`
- `components/`：`EventTimeline` / `StepCard` / `ToolCallCard` / `SanitizeBadge`
- `hooks/`：`useEventStream`(WS, 重连, 补播) / `api`
- Vite 构建 → `gateway/web/dist/`；dev 用 vite proxy → gateway

### 5.5 目录位置
- 前端源码 `web-src/`，构建产物 `gateway/web/dist/`，Gateway 用 `//go:embed` 打进单二进制。

---

## 6. Run 生命周期与异常处理

### 6.1 正常路径
```
浏览器 POST /api/runs
  → 网关: run_id=uuid; sess=StartSession(...); cmd=exec python ... --run-id --session-id --task; 注册 run; cmd.Wait() 兜底收尾
Runtime: emit run.started → 每步 emit runtime.step + CallTool(→kernel 发 tool.*) → emit run.ended → exit(0)
网关 WS hub: 订阅 SubscribeEvents → 按 session→run 过滤 → 推浏览器
```

### 6.2 异常矩阵
| 故障 | 检测 | 处理 | 终止事件 |
|------|------|------|----------|
| Runtime 崩溃 | cmd.Wait() 退出码≠0 且未发 run.ended | 网关发 run.ended(crashed) | run.ended(crashed) |
| Runtime 卡死 | context.WithTimeout 看门狗 | kill 子进程 | run.ended(timeout) |
| DEEPSEEK_API_KEY 缺失 | Runtime 启动秒崩 exit≠0 | 同崩溃路径 | run.ended(crashed) |
| 超 MaxSteps | Kernel Account.Charge 返回超限 → 发 quota.exceeded | Runtime 捕获后 emit run.ended(step_limit) | run.ended(step_limit) |
| Runtime 漏发 run.ended | exit=0 但未收到 run.ended | 网关补发 run.ended(completed) | run.ended(completed) |
| Kernel 不可达 | gRPC 调用失败 | run.ended(error)，拒绝新 run | run.ended(error) |
| 浏览器 WS 断开 | 连接关闭 | run 继续，事件落事件环 | 无 |
| 浏览器重连/迟到订阅 | WS 握手带 run_id | 先补播事件环历史，再续推 | 无 |

### 6.3 决策
- **`run.ended` 是唯一收尾权威**，无论正常/异常。网关看门狗兜底补发，保证浏览器一定能看到 run 收尾。
- **看门狗超时**：MVP 用 `context.WithTimeout` 包 cmd，默认 5 分钟（含 LLM 重试时间）。不做步数级细粒度，留后续。
- **WS 重连补播**：每个 run 维护有界事件环（最近 500 条），重连先发历史再续推。进程重启缓冲丢失为已知简化（事件仍在 Kernel 审计 ledger，可由切片 C 的只读回看补救）。

---

## 7. 安全

### 7.1 网关是新增攻击面，纳入 Kernel 认证边界
- **网关 → Kernel**：同机 Unix socket 0600 保护，**不改**。
- **浏览器 → 网关**（新攻击面）：
  - 网关 HTTP **只监听 127.0.0.1**（localhost-only），不对外。
  - **不做认证**（沿用 LocalAuthenticator 语义）；所有 run 经网关以固定 Identity（user=local）调 Kernel。
  - 阶段 2 加 mTLS/API key 时，认证点在**网关**，Kernel 不动。
- **结论**：网关不削弱现有安全模型；它是 localhost 受信入口，安全权威仍在 Kernel（所有副作用仍过 Pipeline）。

### 7.2 脱敏摘要不泄露
`tool.called.sanitize` 只含字段名+策略，无原始值/脱敏后值（决策 A）。测试需对抗断言：原始值不出现在任何事件。

### 7.3 Runtime 子进程环境变量
`DEEPSEEK_API_KEY` 由网关从自身环境透传给子进程；不在 API 暴露、不写日志、不进事件。

---

## 8. 测试策略（安全测试 > 功能测试）

| 层 | 测什么 | 形式 |
|----|--------|------|
| Kernel | SubscribeEvents 流正确；EmitRuntimeEvent 进 EventBus；tool.called 含 sanitize 摘要；session.ended 被发布；**原始值不出现在任何事件**（对抗断言） | Go testing |
| Gateway | runmgr：正常/崩溃/超时/漏发 run.ended 各路径；事件环补播；WS 按 run 过滤；fork 透传 env；localhost-only 监听 | Go testing + fake Kernel |
| Runtime | loop 发三类事件；不建 session（用传入的）；emit_event 经 gRPC | pytest + mock Kernel |
| Frontend | useEventStream 重连/补播；时间线渲染各事件类型；脱敏 badge | vitest + Testing Library |
| 端到端 | 完整跑数据分析任务，浏览器收到完整事件序列，含 sanitize badge | 手动 + 1 个 playwright e2e |

### 8.1 对抗安全测试（护城河证明，沿用 v2.3 §12.3）新增 2 条
- 经网关提交"读 /etc/passwd"任务 → Kernel Gate 拒，浏览器看到 `tool.denied`。
- 断言 `tool.called` 事件流里**搜不到**任何原始敏感值（如真实手机号模式）。

---

## 9. 成功标准

> **实现状态（2026-06-26）**：以下 6 条全部达成。

1. **实时**：浏览器提交任务后，think/act/observe/工具调用/权限/脱敏/run 收尾**实时**可见。 ✅
2. **卖点亮眼**：四个 demo 卖点（能干活/被脱敏/被管住/能查）在仪表盘一眼可见。 ✅
3. **安全不破**：对抗测试 2 条通过；脱敏摘要无原始值。 ✅（注：对抗用例以 Kernel 层 8 例为主；网关层断言见 `handlers_test.go`/`ws/hub_test.go`）
4. **开闭原则**：Kernel 核心零改动，新增能力全加性。 ✅
5. **健壮收尾**：崩溃/超时/漏发各路径浏览器都能看到 `run.ended`。 ✅
6. **重连无感**：WS 断开重连能补播历史。 ✅

---

## 10. 未决问题（实现计划阶段细化）
- protobuf `Event` message 字段设计（对齐现有 `eventbus.Event` 还是泛化）。
- Gateway 内部包结构细节（接口边界）。
- WS 消息协议格式（每条 event 是 JSON 还是带信封）。
- 看门狗超时是否做成 per-run 可配（MVP 先全局默认）。
- 事件环补播的边界条件（run 已 ended 后的事件环保留多久）。
