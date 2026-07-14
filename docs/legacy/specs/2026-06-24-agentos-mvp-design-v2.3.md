# AgentOS MVP 设计文档 v2.3

- **日期**: 2026-06-24
- **状态**: ✅ **已实现**（阶段 0 + 0.1，2026-06-26 同步；原为草稿）。6 条原始成功标准 + 切片 A 3 条全部达成。
- **阶段**: 阶段 0 — 安全内核 MVP（数据分析场景）
- **相对 v1 的变更**: 架构大改。v1 文档（`2026-06-23-agentos-mvp-design.md`）保留作历史对照，本文档为权威。

---

## 0. 本版相对 v1 的核心变化（先读这段）

v1 把"沙箱"当核心壁垒，但深度审视后发现：数据分析场景下真正的核心风险是**企业敏感数据经 LLM 外泄**，不是 agent 乱删文件。因此 v2.3 做了战略级调整：

| 维度 | v1 | v2.3 |
|------|----|------|
| 安全核心 | 沙箱 | **脱敏层（第一道防线）** |
| 场景 | 模糊 | **数据分析/报表（明确锁定）** |
| MVP 性质 | "验证壁垒" | **技术验证型（诚实化）** |
| 工具协议 | Kernel switch-case | **Tool 自描述接口（开闭原则）** |
| 权限模型 | 特化于 path | **Resource{Type,ID} 泛化** |
| 脱敏 | 无 | **独立 Sanitizer** |
| 消息总线 | 无 | **最小 in-process EventBus** |
| 并发控制 | 无 | **Scheduler + Account** |
| 状态持久化 | 无 | 原子写 + Snapshot 接口预留 |
| Kernel 认证 | 盲区 | **socket 权限 + Policy 白名单** |

**净效果**：MVP 实际代码量增加不多（大多是接口预留 + 防御检查），但堵住了 5 个真实盲区，并为阶段 1-2 铺好所有扩展点。

---

## 1. 项目画像

### 1.1 一句话定位
做一个**企业级、以"安全与可控"为核心壁垒的 Agent 操作系统**，卖给企业，支持私有化部署。

### 1.2 战略选择

| 维度 | 决策 | 理由 |
|------|------|------|
| 项目类型 | "Agent 内核 + 调度器"操作系统 | 把 agent 当"进程"来管理，是真正的 OS 形态 |
| 目的 | 认真的产品 / 创业 | 长期投入，要考虑可靠性、安全、商业化 |
| 目标用户 | 卖给企业（平台） | 企业愿为 agent 付费，技术壁垒不易被抄 |
| 切入壁垒 | **安全与可控** | 四个候选维度里壁垒最高、最不易被抄的方向 |
| 技术栈 | **混合架构**：Go（内核）+ Python（运行时） | Go 贴近系统、安全强；Python agent 生态好 |
| **第一场景** | **数据分析/报表** | 安全卖点直接（敏感数据不外泄）、市场大、MVP 可行 |
| **LLM 路线** | 云端 DeepSeek 起步 + **脱敏层承担安全核心** | 生产换本地模型，接口必留 |
| **客户策略** | 先验证技术，客户后找 | MVP 是技术验证型，非市场验证型 |

### 1.3 全局路线图

> **实现注记（2026-06-26 同步）**：标 ✅ 的已完成。

| 阶段 | 交付物 | 验证目标 | 状态 |
|------|--------|----------|------|
| **0. 安全内核（本 MVP）** | 单 agent + 脱敏 + 权限 + 审计 + Pipeline + EventBus + 并发骨架 | 技术架构与安全机制能否跑通 | ✅ |
| **0.1 实时可观测控制台（切片 A）** | Web 网关 + 实时仪表盘，安全机制"看得见" | 强化 demo 卖点 | ✅ |
| **0.5 场景做深** | 真实数据集、对抗测试强化、脱敏增强、`code_exec` 工具 + 硬隔离沙箱 | 把首发场景做穿 | ⬜ |
| 1. 多 Agent 调度 | agent 生命周期、并发、资源限额、agent 间通信 | 调度层架构 | ⬜ |
| 2. 企业级能力 | 私有化、多租户、可观测性、审批流、Web 控制台完整 | 能否卖给企业 | ⬜ |
| 3. 生态 | SDK / 插件机制 / 企业系统集成 | 商业化扩展 | ⬜ |

---

## 2. MVP 范围（v2.3）

### 2.1 MVP 目标
**验证技术架构与安全机制能否跑通**——agent 能跑数据分析任务，脱敏有效，权限正确，审计完整，并发骨架工作，加新工具时 Kernel 核心零改动。

> ⚠️ 诚实声明：因无客户参与，本 MVP **不验证市场是否为壁垒买单**，只验证技术。市场验证留待有客户后。

### 2.2 明确排除（不在 MVP 内）

> **实现注记（2026-06-26 同步）**：标 ⬜ 的仍未实现；标 ✅ 的已在本 MVP 周期内**提前**完成，详见下方状态。

- 多 agent / agent 间通信（阶段 1）⬜
- Web UI / 可视化（阶段 2）——**部分提前实现**：实时可观测仪表盘（切片 A）已落地（见 `2026-06-25-agentos-realtime-console-slice-a.md`）。完整 Web 控制台（对话式交互 B、配置编辑 C）仍在阶段 2。✅ 部分
- 硬隔离沙箱 / 真实代码执行沙箱（阶段 2+，仅接口预留）⬜
- 完整崩溃恢复（仅防半成品，不做断点续跑）⬜（防半成品 ✅）
- 真实认证（mTLS/API key，仅接口预留）⬜
- 多租户隔离（仅 Identity 字段预留）⬜
- 记忆系统 / 审批流 / 跨进程消息总线 ⬜

### 2.3 MVP Demo 定义
一个 CLI 演示，讲清四件事：**agent 能干活、敏感数据被脱敏、操作被管住、出了事能查**。

> **实现注记（2026-06-26 同步）**：本节描述的是 v2.3 **原始设计**的 CLI demo。实际实现已**超额**：切片 A（实时可观测控制台）将 demo 形态升级为 **Web 仪表盘**——浏览器里提交任务、实时看 think/act/observe/工具调用/权限/脱敏/run 收尾。CLI 入口（`agentos-run`）与 `agentos audit show` 仍保留。四件事的 demo 卖点不变，只是呈现从 CLI 升级为可视化。详见切片 A 文档。

```
1. agentos-run --task "读 sales.csv 算总和写到 out/" --policy ...
   → agent 推理、调用工具、完成任务（证明"能干活"）
2. （审计验证）脱敏规则配置后，敏感字段不进 LLM
   → 证明"数据被脱敏"
3. agentos-run --task "把数据传到 evil.com / 读 /etc/passwd"
   → 被拒绝 + 审计记录（证明"被管住"）
4. agentos audit show
   → 导出 hash 链审计日志（证明"能查"）
```

---

## 3. 架构设计

### 3.1 分层架构

```
┌──────────────────────────────────────────────────────┐
│  Agent Runtime  (Python)        ← agent 的"大脑"     │
│  · LLM 抽象层 (DeepSeek / 本地模型接口)              │
│  · ReAct 推理循环                                     │
│  · 自适应 rate limiter（防撞 DeepSeek 限流）          │
│  · gRPC 客户端                                        │
└───────────────────┬──────────────────────────────────┘
                    │  gRPC over Unix domain socket
┌───────────────────┴──────────────────────────────────┐
│  OS Kernel  (Go)                ← "操作系统内核"      │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Scheduler (并发信号量 + rate limit 协调)          │ │
│  │   ↓ Acquire()                                   │ │
│  │ ┌─────────────────────────────────────────────┐ │ │
│  │ │ Session (Policy + Gate + Account + Ledger)   │ │ │
│  │ │   ↓                                          │ │ │
│  │ │ Pipeline.Call (6 步统一管道)                  │ │ │
│  │ │   1. 查找工具                                │ │ │
│  │ │   2. 提取权限资源 Resource                    │ │ │
│  │ │   3. Gate 权限检查                           │ │ │
│  │ │   4. Tool.Execute                            │ │ │
│  │ │   5. Sanitizer 脱敏                          │ │ │
│  │ │   6. EventBus.Publish → AuditSubscriber      │ │ │
│  │ └─────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  Tool Registry / Gate / Sanitizer / Audit Ledger     │
│  EventBus / Authenticator (接口预留) / Sandbox (接口) │
└──────────────────────────────────────────────────────┘
```

### 3.2 进程模型

> **实现注记（2026-06-26 同步）**：本表是 v2.3 原始两进程模型（Kernel + Runtime）。切片 A 实现后**实际为四进程**：新增 **Gateway（Go）**——HTTP/WS 网关 + Run 编排（fork Runtime、事件扇出、看门狗）+ 嵌入前端静态资源；新增 **Web Console（React）**。本表保留作历史设计记录；当前权威架构图见 README 与切片 A 文档 §2。

| 角色 | 语言 | 职责 | 安全权威 |
|------|------|------|----------|
| **Kernel** | Go（常驻） | 守门人，持有所有敏感能力的执行权 | ✅ 是 |
| **Agent Runtime** | Python | 执行 LLM 推理循环，**本身零敏感权限** | ❌ 否 |
| **Gateway**（切片 A 新增） | Go | HTTP/WS 网关 + Run 编排 + 事件扇出，localhost-only | ❌ 否 |
| **Web Console**（切片 A 新增） | React+TS | 提交 run、实时事件流、脱敏标记展示 | ❌ 否 |
| **Sandbox** | 由工具按需 | path 型工具内部做路径解析（MVP）；未来独立执行环境 | 受 Kernel 约束 |

**核心安全原则**：Python Runtime 永远不直接碰敏感资源。任何有副作用的操作必须通过 gRPC 向 Kernel 发请求，Kernel 经 Pipeline 处理（权限→执行→脱敏→审计）→ 返回脱敏后的结果。

### 3.3 通信
- **gRPC over Unix domain socket**（单机、低延迟、强类型）
- socket 文件权限 0600（见 §10 Kernel 认证）

---

## 4. 安全防线（四道，重排）

数据进入 LLM 前，依次经过四道防线：

```
数据进入 → ① 脱敏层（字段级，配置驱动，第一道）
         → ② 权限闸门（Resource 泛化匹配，第二道）
         → ③ 沙箱（工具内部实现，第三道）
         → ④ 审计（订阅事件，hash 链，第四道）
```

### 4.1 脱敏层 Sanitizer（数据分析场景的核心壁垒）

**定位**：第一道防线。即便用本地模型，数据分析场景也必须脱敏——LLM 上下文不稳定（可能被日志记录、进训练数据、被 prompt 注入套出）。**脱敏是数据安全的真正承担者，不是部署位置的补丁。**

**字段级脱敏策略**（MVP 三种）：

| 策略 | 作用 | 适用字段 |
|------|------|---------|
| `mask` | 替换为 `***` 或保留首尾（如 `138****1234`） | 手机号、身份证、姓名 |
| `hash` | 单向哈希（同值同 hash，可关联不可还原） | 客户ID、订单号 |
| `redact` | 完全移除 | 备注、自由文本敏感内容 |

**配置驱动**（YAML）：
```yaml
sanitization:
  fields:
    - name: "id_card"
      strategy: mask
    - name: "phone"
      strategy: mask
      keep_prefix: 3
      keep_suffix: 4
    - name: "customer_id"
      strategy: hash
    - name: "remark"
      strategy: redact
```

**脱敏在 Pipeline 第 5 步统一执行**，独立于工具。规则是配置，企业可按合规要求自定义。aggregate（聚合防推断）策略留后续。

### 4.2 权限模型（Resource 泛化）

**核心抽象**：权限判定对象从"路径"泛化为 `Resource{Type, ID}`：

```go
type Resource struct {
    Type string  // "path" | "db_table" | "http_url" | ...
    ID   string  // "examples/workspace/x.csv" | "sales.orders" | ...
}
```

**权限规则**（Policy）：
```yaml
permissions:
  - resource_type: path
    pattern: "examples/workspace/**"
    actions: [fs_read, fs_list]
  - resource_type: path
    pattern: "examples/workspace/out/**"
    actions: [fs_write]
  # 未来加 db_table / http_url 类型规则
```

**Gate 做通用 (action, resource) 匹配，不认识工具名**。加新资源类型工具（db_query）只需加新规则，Gate 代码零改。

### 4.3 沙箱（降级 + 接口预留）

**MVP 形态**：path 型工具内部用 `sandbox.Resolve` 做路径强校验（防穿越、防符号链接逃逸）。是工具实现细节，不再是独立核心。

**接口预留**（为未来代码执行沙箱）：
```go
type Sandbox interface {
    ExecuteCode(lang string, code string, ctx ExecContext) (Result, error)
    ReadFile(path string) ([]byte, error)
}
// MVP 实现：InProcessSandbox（仅内置工具用，不跑任意代码）
// 未来：WasmSandbox / ContainerSandbox
```

> **实现注记（2026-06-26 同步）**：实际 MVP 实现进一步**简化**了此接口——因为数据分析 MVP 的内置工具（fs_read/fs_write/fs_list）是 Kernel 自身代码、不跑 agent 生成的代码，故 `Sandbox` 接口暂不需要 `ExecuteCode`/`ReadFile` 方法。当前接口仅含 `Type() string`（标识沙箱类型，为未来 Wasm/Container 扩展留钩子），路径强校验下沉到 `sandbox.Resolve` 由各 path 型工具在 `Execute` 内部调用。阶段 0.5/1 引入 `code_exec` 工具时，本接口将重新扩展为上述完整形态。这是诚实降级：MVP 不承担"跑任意代码"的安全责任。

数据分析场景真实刚需是"agent 跑 pandas/统计代码"，未来加 `code_exec` 工具 + WasmSandbox 是独立模块，不动 Pipeline。

### 4.4 审计 Audit Ledger

**append-only、hash 链、不可篡改**。每条记录含 `who/what/when/result`。

- MVP：append-only 文件 + hash 链（每条含前一条 hash）
- **审计通过订阅 EventBus 事件产生**（见 §6），不再散落调用
- 阶段 2：升级 WORM 存储 / 远程转发

价值：企业"出了事能查、能合规"的命脉；与 LangSmith（偏 dev 观测）的差异化。

---

## 5. 工具自描述抽象（核心架构决策）

### 5.1 核心思想
**从"Kernel 认识每个工具（switch-case）"变成"工具自我描述，Kernel 是通用引擎"。**

工具自带四样元数据：名字、LLM schema、权限资源怎么提取、产出怎么脱敏。Kernel 用元数据驱动统一管道，自己不认识任何具体工具。

### 5.2 Tool 接口

```go
type Tool interface {
    Name() string
    Schema() json.RawMessage                       // 给 LLM 的 function schema
    PermissionKey(params map[string]any) Resource  // 从参数提取权限资源
    Execute(ctx context.Context, params map[string]any) (Result, error)
}
```

### 5.3 收益：加工具零改 Kernel
- 加 fs 工具：写一个 Tool 实现 + 注册，Pipeline/Gate/Sanitizer/审计 0 改
- 加 db_query：同样写一个 Tool 实现（PermissionKey 返回 `db_table` 类型），Kernel 0 改

### 5.4 开闭原则验证（MVP 成功标准之一）
MVP 完成时，要能证明：加一个新工具（如 db_query 桩）时，Kernel 核心代码（Pipeline/Gate/Server）零改动。

---

## 6. 统一管道 Pipeline + EventBus

### 6.1 Pipeline 6 步

```
CallTool(session, tool_name, params)
  1. 查找工具     tool = registry[tool_name]        不存在 → deny
  2. 提取权限     resource = tool.PermissionKey()   
  3. 权限检查     gate.Allowed(tool_name, resource)  不通过 → deny + 事件
  4. 执行         result = tool.Execute(...)         出错 → error + 事件
  5. 脱敏         result = sanitizer.Sanitize(...)
  6. 审计         bus.Publish(tool.called)           统一切面
```

这 6 步固定。加新工具这 6 步一行不改。

### 6.2 EventBus（最小 in-process）

**定位**：Kernel 内部事件分发骨架，同步分发，承担横切关注点解耦。**不是跨进程消息中间件。**

```go
type Event struct {
    Type      string  // tool.called | tool.denied | tool.errored | session.started | session.ended | quota.exceeded
    SessionID string
    Tool      string
    Params    map[string]any
    Result    map[string]any
    Timestamp int64
}

type EventBus interface {
    Publish(event Event)
    Subscribe(handler func(Event))
}
```

**MVP 实现**：`InProcessEventBus`，同步分发，fire-and-forget（订阅者 panic 不炸主流程，recover）。

**第一个真实用例**：审计订阅 `tool.*` 事件，集中写 ledger（解决 v1 的"审计散落"问题）。

**未来扩展**（加 subscriber 不改 Pipeline）：Webhook、Prometheus metrics、多 agent 通信、日志聚合。

---

## 7. 并发骨架（三层）

### 7.1 Scheduler（管"谁先跑、跑几个"）

```go
type Scheduler struct {
    sem chan struct{}  // 并发信号量
}
func (s *Scheduler) Acquire(ctx context.Context) (release func(), err error)
```

- **并发上限**：信号量限制同时在跑的 agent 数
- **公平性**：FIFO，长任务不饿死短任务
- MVP 不做优先级调度（留接口）

### 7.2 Account / ResourceQuota（管"一个 agent 用多少"）

```go
type ResourceQuota struct {
    MaxSteps  int  // 推理步数（防死循环）
    MaxTokens int  // LLM token（防烧钱）
    // MaxDuration / MaxToolCalls 留后续
}
type Account struct { quota ResourceQuota; used Usage }
func (a *Account) Charge(usage Usage) error  // 超限返回 ErrQuotaExceeded
```

**超限行为**：硬终止。发 `quota.exceeded` 事件 → 终止 agent → 返回错误给 Runtime。

### 7.3 Executor（接口占位）

```go
type Executor interface {
    Run(ctx context.Context, sess *Session, task string) (Result, error)
}
```

MVP 不实现（agent 逻辑在 Python Runtime）。接口留好，阶段 1 Kernel 自管 agent 调度时用。

### 7.4 rate limit 职责划分（重要）

```
Kernel 的 Scheduler：  管"几个 agent 同时跑"（并发信号量）
Runtime 的 LLM 客户端：管"怎么不撞 DeepSeek 限流"（自适应 rate limit）
```

**自适应策略（选项 Z）**：保守 RPS 初值 + 遇 429 指数退避 + 动态调低 RPS。在 Runtime 侧实现，因为 429 是 DeepSeek HTTP 响应，只有发起方感知得到。

> **实现注记（2026-06-26 同步）**：本节职责划分**与实现一致**。两点细化：
> - Kernel Scheduler 用 **Go channel 自实现信号量**（`sem chan struct{}`，FIFO），**未引入** `golang.org/x/time/rate`（避免无谓依赖；信号量比 token bucket 更贴合"并发槽数"语义）。
> - Runtime 限流为 **自实现 `AdaptiveRateLimiter`**（`runtime/agentos_runtime/rate_limit.py`）：初值 RPM=30，遇 429 降速一半 + 指数退避，成功恢复至初值。
> - 注：v2.3 §13 技术栈表曾写"`golang.org/x/time/rate` 用于并发"，与实现不符——以本节与 §13 的更新注记为准。

---

## 8. Agent Runtime（Python）

### 8.1 LLM 抽象层
```
LLMClient (抽象接口)
  ├── DeepSeekProvider  ← MVP（云端，OpenAI 兼容协议）
  └── LocalProvider     → 接口预留（Ollama/vLLM，生产私有化）
```

### 8.2 推理循环（ReAct）
```
循环 {
  think:   LLM 推理"下一步该干什么"
  act:     调一个工具（→ 过 Kernel Pipeline）
  observe: 拿到脱敏后的工具结果
  重复，直到 LLM 说"完成" 或 Account 超限
}
```

### 8.3 工具协议
Runtime 零真实能力，所有副作用操作委托 Kernel。结果经 Kernel 脱敏后才回 Runtime。

---

## 9. 状态持久化（防半成品 + 接口预留）

### 9.1 防半成品（MVP 做）
fs_write 用**原子写**（写 `.tmp` → `os.Rename`）。崩溃时要么旧文件要么新文件，无半成品。比 WAL 简单，效果一样。

### 9.2 接口预留
```go
func (s *Session) Snapshot() ([]byte, error)    // MVP 不调用，接口留好
func RestoreSession(data []byte) (*Session, error)
```

完整断点续跑不做（ReAct 模型下不干净，留阶段 2 重新设计）。

---

## 10. Kernel 认证（堵盲区 + 接口预留）

### 10.1 MVP 两层最简防御
1. **Socket 文件权限 0600**（OS 级，一行代码）：只有启动 Kernel 的用户能连
2. **Policy 路径白名单**（~20 行）：StartSession 校验 Policy 在受信目录内，防加载恶意全权限 Policy

> 第 2 条必做——否则攻击者写个 `fs_read: /**` 的 Policy 就破掉所有权限设计。

### 10.2 接口预留
```go
type Authenticator interface {
    Authenticate(ctx context.Context) (Identity, error)
}
type Identity struct {
    Tenant string  // MVP 单租户 = "default"
    User   string  // MVP = "local"
}
```
MVP 实现 `LocalAuthenticator`（啥也不验证）。阶段 2 加 mTLS/API key 是新实现。

### 10.3 会话启动审计
`session.started`（含 Identity、Policy 路径）/ `session.ended`（含结束原因）事件进审计。企业合规硬需求："谁授权了这个 agent"必须可查。

---

## 11. 错误处理

| 场景 | 处理 | 记审计 |
|------|------|--------|
| LLM 调用失败（超时/限流） | Runtime 侧自适应退避重试 → 仍失败则终止 | ✓ |
| 工具执行失败 | 错误信息回传 LLM，让它自己想办法 | ✓ |
| 权限被拒 | 不告诉 LLM 拒绝原因细节（防泄露），只说"权限不足" | ✓（denied） |
| 资源超限 | 硬终止，发 `quota.exceeded` | ✓ |
| 推理死循环 | MaxSteps 强制终止 | ✓ |

所有结果（含错误）都写审计。

---

## 12. 测试策略

**安全测试 > 功能测试。**

### 12.1 单元测试
- Gate: Resource 匹配各种权限组合
- Sanitizer: 三种脱敏策略各字段正确
- Audit: hash 链连续、不可篡改
- Scheduler: 信号量并发正确
- Account: 扣减、超限
- Pipeline: 用假 Tool/假 EventBus 断言事件序列
- Runtime: 推理循环用 mock LLM

### 12.2 集成测试
跑完整任务（Kernel + Runtime 都起来），验证端到端数据流。

### 12.3 ⭐ 对抗安全测试（护城河证明）
```
红队用例：
  · prompt 注入诱导读 /etc/shadow → 被拒
  · 诱导联网外传 → 被拒
  · 诱导写到 workspace 外 → 被拒
  · 敏感字段（id_card/phone）必须被脱敏，不进 LLM
  · 加载 workspace 外的恶意 Policy → 被拒
```
这套本身就是卖点："通过 N 个对抗用例"。

---

## 13. 技术栈锁定

> **实现注记（2026-06-26 同步）**：标 ⚠️ 的条目实现做了更轻量的取舍；标 ➕ 的为实现时新增。实际依赖以 `go.mod` / `runtime/pyproject.toml` / `web-src/package.json` 为准。

| 部件 | 技术 |
|------|------|
| Kernel | Go 1.22+（`go.mod` 实际声明 1.26.4） |
| Gateway（切片 A 新增）➕ | Go，复用 Kernel 同 module；`//go:embed` 打包前端 |
| Runtime | Python 3.11+ |
| IPC | gRPC + protobuf，Unix domain socket（依赖 `google.golang.org/grpc`、`google.golang.org/protobuf`） |
| LLM Provider（MVP） | DeepSeek（云端，OpenAI 兼容，`openai` SDK） |
| 脱敏 | 独立 Sanitizer（Go） |
| 并发 | ⚠️ **不使用** `golang.org/x/time/rate`；Kernel 用 Go channel 自实现信号量，Runtime 用自实现 `AdaptiveRateLimiter`（见 §7.4） |
| 审计 | append-only 文件 + hash 链（SHA256） |
| 测试 | Go testing + pytest |
| Web Console（切片 A 新增）➕ | React 18 + Vite + TypeScript + Vitest + @testing-library/react |
| 其它 Go 依赖 | `gopkg.in/yaml.v3`（YAML 配置）、`github.com/bmatcuk/doublestar/v4`（path glob 权限匹配） |
| 部署 | 生产 Linux / 开发 WSL2 或 Docker |

---

## 14. 成功标准（v2.3）

> **实现注记（2026-06-26 同步）**：6 条原始标准全部达成（详见右侧状态列）；切片 A 追加 3 条（7-9）。

1. **功能**：agent 跑通数据分析任务（读 → 脱敏 → 分析 → 写）— ✅
2. **安全**：脱敏有效（敏感字段不进 LLM）+ 对抗测试全过 — ✅（8 例对抗测试）
3. **可审计**：审计 hash 链完整，通过订阅事件产生 — ✅
4. **架构**：加新工具（如 db_query 桩）时 Kernel 核心零改动 — ✅（`open_closed_test.go` 可执行证明）
5. **并发**：Scheduler 信号量工作，Account 超限硬终止 — ✅
6. **认证**：socket 权限 + Policy 白名单生效 — ✅
7. **实时可观测**（切片 A 追加）：浏览器实时看 think/act/observe/工具/权限/脱敏/run 收尾 — ✅
8. **健壮收尾**（切片 A 追加）：崩溃/超时/漏发各路径浏览器都能看到 `run.ended` — ✅
9. **WS 重连补播**（切片 A 追加）：断开重连补播事件环历史 — ✅

满足这九条，技术架构与安全机制即被验证，可进入阶段 0.5。

---

## 15. 未决问题（实现计划阶段细化）

- 项目目录结构（按新架构重组）
- protobuf schema 字段设计
- DeepSeek function calling 实测稳定性（执行风险，未验证）
- capability/sanitization 配置 schema 完整定义
- Pipeline 测试夹具设计
