# AgentOS

> 企业级、以**安全与可控**为核心壁垒的 Agent 操作系统。让 AI agent 在严格受控的沙箱里执行任务——每个有副作用的操作都经过权限闸门、字段级脱敏、不可篡改的审计链。

**当前阶段：MVP（阶段 0 — 安全内核）**。已通过技术验证，含真实 LLM（DeepSeek）端到端 demo。

---

## 为什么需要 AgentOS

LLM 是不可控的——它会被 prompt 注入欺骗、会产生幻觉、会乱来。但企业要的是**可控的自动化**。AgentOS 的核心命题是：

> **给不可控的 agent 套上硬约束。** agent 能完成数据分析等任务，但它越不过权限边界，敏感数据不会泄露给 LLM，且每一次操作都可追溯。

四道安全防线（这是 AgentOS 的壁垒所在）：

```
数据进入 LLM 前，依次经过：
  ① 脱敏层（字段级，配置驱动）—— 第一道，PII 不进 LLM 上下文
  ② 权限闸门（Resource 泛化匹配）—— 第二道，越界操作被拒
  ③ 沙箱（路径强校验 + 接口预留）—— 第三道，防穿越/逃逸
  ④ 审计（hash 链，不可篡改）—— 第四道，事后可追溯
```

**关键设计：脱敏是数据安全的真正承担者，不是部署位置的补丁。** 即便用本地模型，PII 也必须脱敏（上下文不稳定、可能进训练数据、可能被注入套出）。生产部署换本地模型时，脱敏层依然在工作。

---

## 架构

四个进程协作，**Kernel 是事件枢纽**：

```
                       ┌──────────────────────────┐
                       │   Web Console (browser)  │
                       │   React + Vite           │
                       └────────────┬─────────────┘
                              HTTP + WebSocket
                       ┌────────────┴─────────────┐
                       │     Gateway (Go)         │
                       │  · HTTP API + WS Hub     │
                       │  · Run Manager（编排）   │
                       │  · 嵌入前端静态资源      │
                       └────────────┬─────────────┘
                          gRPC │        │ 拉起/守护
              SubscribeEvents │        ▼
  ┌───────────────────────────┴──┐  ┌─────────────────────┐
  │        Kernel (Go)           │  │   Runtime (Python)  │
  │  · Pipeline（6 步统一管道）  │◄─┤  · DeepSeek 客户端  │
  │  · Gate（Resource 泛化权限） │  │  · ReAct 循环       │
  │  · Sanitizer（脱敏）         │  │  · 自适应 rate limit│
  │  · Audit Ledger（hash 链）   │  │                     │
  │  · EventBus（事件枢纽）      │  │  零敏感权限：所有   │
  │  · Scheduler + Account       │  │  操作委托给 Kernel  │
  │  · Authenticator（接口预留） │  └─────────────────────┘
  └──────────────────────────────┘
          gRPC over Unix socket
```

| 进程 | 语言 | 职责 | 安全权威 |
|------|------|------|----------|
| **Kernel** | Go（常驻） | 守门人：权限/脱敏/审计/调度，持有所有敏感能力的执行权 | ✅ 唯一 |
| **Runtime** | Python | agent 的"大脑"：LLM 推理 + ReAct 循环，**本身零敏感权限** | ❌ |
| **Gateway** | Go | HTTP/WS 网关，编排 run（启动 Runtime、管理 session、扇出事件）| ❌ |
| **Web Console** | React | 实时控制台：提交 run、看事件流/工具调用/脱敏标记 | ❌ |

### 核心抽象：工具自描述（开闭原则）

Kernel **不认识任何具体工具**。每个工具自带元数据（名字、LLM schema、权限资源怎么提取）。加一个新工具（如 `db_query`）只需：
1. 写一个 `Tool` 接口实现
2. 注册它

Pipeline / Gate / Sanitizer / EventBus **零行改动**。这一点由架构验证测试（`kernel/test/architecture/`）可执行地证明。

### 统一事件流

Kernel 的 `EventBus` 是事件枢纽。Runtime 把推理事件（`run.started`、`runtime.step`、`run.ended`）通过 gRPC 灌进 Kernel 的 EventBus，所有事件统一从 Kernel 流出 → Gateway 订阅 → WebSocket 扇出给前端。审计也通过订阅 `tool.*` 事件产生（集中、不散落）。

---

## 项目结构

```
AgentOS/
├── kernel/              # Go 内核（安全 + 调度 + Pipeline）
│   ├── cmd/agentos/     # CLI: agentos serve / audit show
│   ├── internal/
│   │   ├── resource/    # Resource{Type,ID} 泛化权限对象
│   │   ├── policy/      # Policy + Gate（权限匹配）
│   │   ├── sanitize/    # 脱敏层（mask/hash/redact）—— 第一道防线
│   │   ├── audit/       # hash 链账本 + 事件订阅者
│   │   ├── eventbus/    # in-process 同步事件总线
│   │   ├── sandbox/     # Sandbox 接口 + path 校验
│   │   ├── tools/       # Tool 接口 + fs_read/fs_write/fs_list
│   │   ├── session/     # Session + Account（资源限额）
│   │   ├── scheduler/   # 并发信号量
│   │   ├── pipeline/    # 6 步统一管道（核心）
│   │   ├── auth/        # Authenticator + Policy 白名单
│   │   └── server/      # gRPC 服务端
│   └── test/
│       ├── adversarial/ # 对抗安全测试（8 例，护城河证明）
│       └── architecture/# 架构验证（开闭原则证明）
├── gateway/             # Go 网关（HTTP/WS + Run 编排 + 嵌入前端）
├── runtime/             # Python 运行时（DeepSeek + ReAct）
│   └── agentos_runtime/
├── web-src/             # React 前端（Vite）
├── pb/                  # gRPC 契约（.proto 源 + Go 生成代码）
├── examples/            # demo 工作区 + 策略 + 脱敏规则（受信目录）
└── docs/superpowers/    # 设计文档 + 实现计划（中文）
```

---

## 快速开始

### 环境要求

- **Go 1.22+**（开发用 1.26）
- **Python 3.11+**
- **protoc + protoc-gen-go**（仅改 proto 时需要）
- **Node.js 18+**（仅构建前端时需要）
- **DeepSeek API key**（或自行对接其它 OpenAI 兼容模型）
- **Linux / WSL2**（生产/运行推荐；Windows 可开发但自编译二进制受 WDAC 等策略限制）

### 1. 安装依赖

```bash
# Go 依赖
go mod tidy

# Python 依赖（建议用 venv/conda 隔离）
cd runtime && pip install -e . && cd ..

# 前端依赖（构建控制台）
cd web-src && npm install && npm run build && cd ..
```

### 2. 设置 DeepSeek key

```bash
export DEEPSEEK_API_KEY="sk-你的key"
```

### 3. 端到端 demo（三进程协作）

**终端 1 — 启动 Kernel**（gRPC over Unix socket）：
```bash
go run ./kernel/cmd/agentos serve -socket ./agentos.sock -audit-dir ./audit
```

**终端 2 — 启动 Gateway**（HTTP + WS，嵌入前端，编排 Runtime）：
```bash
go run ./gateway/cmd/agentos-gateway -kernel-socket ./agentos.sock -http 127.0.0.1:8080
```

**终端 3 — 用控制台**：
打开浏览器访问 `http://127.0.0.1:8080`，提交一个 run：
- 选 policy：`examples/policies/data_analyst.yaml`
- 选 sanitization：`examples/sanitization/pii_rules.yaml`
- 任务示例：`Read examples/workspace/sales.csv, compute the total amount, write to examples/workspace/out/total.txt`

控制台会实时显示 agent 的推理步骤、工具调用、脱敏标记。

### 4. 查看审计日志

```bash
go run ./kernel/cmd/agentos audit show <session-id>
```
输出每条操作（who/what/when/result），并校验 hash 链完整性。

---

## 安全特性

### 四道防线（详见架构图）

| 防线 | 机制 | 实现 |
|------|------|------|
| ① 脱敏 | 字段级，mask/hash/redact 三策略 | `sanitize` 包，YAML 配置驱动 |
| ② 权限 | Resource{Type,ID} 泛化匹配 | `policy` 包，Gate 不认识工具名 |
| ③ 沙箱 | 路径强校验 + Sandbox 接口预留 | `sandbox` 包，MVP 软隔离 |
| ④ 审计 | append-only + SHA256 hash 链 | `audit` 包，篡改可检测 |

### 对抗测试（护城河证明）

`kernel/test/adversarial/` 包含 8 个对抗用例，全部通过：

```
✓ 读取 /etc/shadow 被拒
✓ 读取 Windows SAM 被拒
✓ 路径穿越（../../../etc/passwd）被拒
✓ workspace 外写入被拒
✓ 未知工具（shell_exec）被拒
✓ 未知资源类型（db_table）被拒
✓ 网络访问被拒
✓ PII 字段（phone/customer_id/remark）被脱敏，非 PII（amount）不动
```

### Kernel 认证（MVP 两层）

- **Socket 权限 0600**：只有启动 Kernel 的 OS 用户能连
- **Policy 路径白名单**：StartSession 校验 Policy 在受信目录内，防加载全权限恶意 Policy
- **接口预留**：`Authenticator` 接口为未来 mTLS/API key 留口子（MVP 用 LocalAuthenticator）

---

## 测试

```bash
# 全部 Go 测试（含对抗 + 架构验证）
go test ./...

# Python 测试
cd runtime && pytest -v && cd ..
```

测试覆盖（约 90 个测试）：
- 内核基础：Resource/Policy/Gate/Sanitizer/Ledger/EventBus/Sandbox/Tools/Session/Scheduler/Pipeline/Auth
- 对抗安全：8 个红队用例
- 架构验证：开闭原则（加 db_query 工具零改 Kernel）
- Runtime：rate limiter / kernel client / ReAct loop

---

## 技术栈

| 层 | 技术 |
|----|------|
| Kernel / Gateway | Go 1.22+ |
| Runtime | Python 3.11+，OpenAI SDK（DeepSeek 兼容） |
| IPC | gRPC + protobuf，Unix domain socket |
| 前端 | React + Vite + TypeScript |
| 审计 | append-only 文件 + SHA256 hash 链 |
| 并发 | Go 信号量 + 资源限额（Account） |

---

## 路线图

- ✅ **阶段 0 — 安全内核 MVP**（当前）：单 agent + 脱敏 + 权限 + 审计 + Pipeline + EventBus + 并发骨架 + Gateway + Web 控制台
- ⬜ **阶段 1 — 多 Agent 调度**：agent 生命周期、并发、agent 间通信
- ⬜ **阶段 2 — 企业级能力**：私有化部署、多租户、可观测性、审批流（human-in-the-loop）、硬隔离沙箱（容器/microVM）
- ⬜ **阶段 3 — 生态**：SDK / 插件机制 / 企业系统集成

---

## 文档

设计文档与实现计划（中文）在 `docs/superpowers/`：
- `specs/2026-06-24-agentos-mvp-design-v2.3.md` — 完整设计文档
- `plans/2026-06-24-agentos-mvp-v2.3.md` — 28 任务实现计划

---

## 状态

本项目处于 **MVP 技术验证阶段**，尚未用于生产。欢迎交流，但请勿直接用于企业生产环境（硬隔离沙箱、完整认证等企业级能力尚未实现）。
