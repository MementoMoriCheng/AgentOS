# AgentOS

> 企业级、以**安全与可控**为核心壁垒的 Agent 操作系统。让 AI agent 在严格受控的沙箱里执行任务——每个有副作用的操作都经过权限闸门、字段级脱敏、不可篡改的审计链。

> ⚠️ **实现状态（2026-07，Week 6 完成）**：当前实现是 `cp/`（Python 控制面，V2 架构）。`kernel/`、`gateway/`、`runtime/`、`pb/`（Go + gRPC + 旧 Python 运行时）为 **legacy**，保留作历史参考，不再开发。下方有独立的 legacy 说明。
>
> **Python 控制面启动：** `conda run -n agentos python -m cp.server.cli serve`（默认 fakeredis + mock LLM，零配置）。HTTP + WebSocket API 复刻旧 gateway 契约，前端 `web-src/` 零改对接。详见 [V2 架构设计](docs/AgentOS架构设计重点关注V2.md)。

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

## 架构（V2，Python 控制面）

V2 架构是**五平面**设计（详见 [V2 架构设计](docs/AgentOS架构设计重点关注V2.md)）：

```
                       ┌──────────────────────────┐
                       │   Web Console (browser)  │
                       │   React + Vite           │
                       └────────────┬─────────────┘
                              HTTP + WebSocket
                       ┌────────────┴─────────────┐
                       │   cp/server (FastAPI)    │
                       │  · HTTP API + WS Hub     │
                       │  · RunManager（编排）    │
                       │  · 托管前端静态资源      │
                       └────────────┬─────────────┘
                                    │
              ┌─────────────────────┴──────────────┐
              │        cp/ 控制面核心（单进程）       │
              │  · Pipeline / PrimitiveExecutor      │
              │    （6 步统一管道 + 7 原子原语 +      │
              │     4 复合操作）                      │
              │  · Gate（Resource 泛化权限）         │
              │  · Sanitizer（脱敏）                 │
              │  · Audit Ledger（hash 链）           │
              │  · EventBus（双总线：审计 + 消息）   │
              │  · Scheduler + Checkpoint            │
              │  · Harness Router（框架适配）        │
              │  · LLM 客户端（DeepSeek / Mock）     │
              └─────────────────────┬───────────────┘
                                    │ StatePort
                       ┌────────────┴─────────────┐
                       │     Redis（State Plane）  │
                       │  · 会话状态 + checkpoint  │
                       │  · Run 元数据/事件        │
                       │  · 消息总线 Stream        │
                       └──────────────────────────┘
```

| 组件 | 职责 | 实现位置 |
|------|------|---------|
| **控制面** | 编排 + 安全管线 + agent loop，本身无状态 | `cp/` |
| **State Plane** | Redis（会话/checkpoint/run 事件/消息总线） | `cp/adapters/local_state.py`、`redis_bus.py` |
| **执行面** | 沙箱（Local 进程内 / Docker 接口预留） | `cp/adapters/local_sandbox.py`、`docker_sandbox.py` |

### 核心抽象：原语自描述（开闭原则）

控制面**不认识任何具体原语**。每个原语自带元数据（名字、LLM schema、权限资源怎么提取）。加一个新原语只需：
1. 写一个 `Primitive` 协议实现
2. 注册它

Pipeline / Gate / Sanitizer / EventBus **零行改动**。这一点由架构验证测试（`cp/tests/architecture/`）可执行地证明。

### 统一事件流

`EventBus` 是事件枢纽。控制面的所有操作（`tool.called`、`primitive.called`、`run.started/ended`）都经总线流出 → 审计订阅者写 hash 链 → WS 扇出给前端。双总线设计：审计总线（InProcess，1 参 `Event`）+ 消息总线（Redis Stream，2 参 `topic/payload`，供 pub/sub/复合操作用）。

---

## 项目结构

```
AgentOS/
├── cp/                  # 【当前实现】Python 控制面（V2 架构）
│   ├── server/          # FastAPI HTTP + WebSocket 服务层
│   │   ├── app.py       # 复刻旧 gateway API 契约
│   │   ├── runmgr.py    # 异步 Run 生命周期 + 事件收集
│   │   ├── redis_store.py # Run 状态外部存储（跨副本可观测）
│   │   └── cli.py       # python -m cp.server.cli serve
│   ├── primitives/      # 7 原子原语 + 4 复合操作 + executor + registry
│   ├── pipeline/        # 6 步统一管道
│   ├── policy/          # Policy + Gate（权限匹配）
│   ├── sanitize/        # 脱敏层（第一道防线）
│   ├── audit/           # hash 链账本
│   ├── eventbus/        # 异步事件总线（审计）
│   ├── adapters/        # Port 适配器（local_sandbox/state、redis_bus、docker）
│   ├── orchestration/   # 多 agent 编排模式（顺序链 + fan-out/fan-in）
│   ├── harness/         # V2 Part 2 Harness 适配层
│   ├── llm/             # DeepSeek + Mock 客户端
│   ├── checkpoint.py    # 故障恢复（快照 + 重水合）
│   ├── scheduler/       # 并发限流
│   └── tests/           # 196 tests（含 8 对抗用例）
├── web-src/             # React 前端（Vite，API 契约已被 cp/ 复刻）
├── examples/            # demo 工作区 + 策略 + 脱敏规则（受信目录，cp/ 仍读）
├── kernel/              # 【legacy】Go 内核（V1 架构，不再开发）
├── gateway/             # 【legacy】Go 网关（V1 架构，不再开发）
├── runtime/             # 【legacy】Python 运行时（V1，不再开发）
├── pb/                  # 【legacy】gRPC 契约（V1）
├── docs/
│   ├── AgentOS架构设计重点关注V2.md  # V2 架构 SSOT（当前权威）
│   ├── superpowers/plans/            # Week 1–6 Python cp/ 实现计划
│   ├── legacy/                       # V1（Go）设计文档（历史参考）
│   └── enterprise-java-design/       # 企业级 Java 设计探索（非当前实现）
└── pytest.ini
```

---

## 快速开始

### 环境要求

- **Python 3.11+**（conda 环境名 `agentos`）
- **Node.js 18+**（仅构建前端时需要）
- **DeepSeek API key**（可选；不配则用 mock LLM）

### 1. 安装依赖

```bash
# Python 依赖（建议用 conda 隔离）
conda create -n agentos python=3.11 -y && conda activate agentos
pip install fastapi uvicorn httpx websockets fakeredis redis openai pyyaml pytest pytest-asyncio

# 前端依赖（可选，构建控制台）
cd web-src && npm install && npm run build && cd ..
```

### 2. 启动控制面

```bash
# 默认：fakeredis + mock LLM（零配置，本地开发最快）
conda run -n agentos python -m cp.server.cli serve
# → http://127.0.0.1:8080

# 真实 LLM（可选）
export DEEPSEEK_API_KEY="sk-你的key"
conda run -n agentos python -m cp.server.cli serve --llm real

# 真实 Redis（可选，多副本时需要）
conda run -n agentos python -m cp.server.cli serve --redis-url redis://localhost:6379
```

启动后：
- **`/docs`** — FastAPI Swagger UI（交互式试每个 API）
- **`/api/policies`** — 列出可用策略
- **`/`** — React 控制台（若已 `npm run build`）

### 3. 用控制台

打开浏览器访问 `http://127.0.0.1:8080`，提交一个 run：
- 选 policy：`data_analyst.yaml`
- 选 sanitization：`pii_rules.yaml`
- 任务示例：`Read examples/workspace/sales.csv, compute the total amount, write to examples/workspace/out/total.txt`

控制台实时显示 agent 的推理步骤、工具调用、脱敏标记。

### 4. 测试

```bash
# 全回归（196 passed, 9 skipped）
conda run -n agentos python -m pytest cp/ -v

# 对抗用例（8 例，护城河证明）
conda run -n agentos python -m pytest cp/tests/adversarial/ -v
```

---

## 安全特性

### 四道防线

| 防线 | 机制 | 实现 |
|------|------|------|
| ① 脱敏 | 字段级，mask/hash/redact 三策略 | `cp/sanitize/`，YAML 配置驱动 |
| ② 权限 | Resource{Type,ID} 泛化匹配 | `cp/policy/`，Gate 不认识工具名 |
| ③ 沙箱 | 路径强校验 + Sandbox 接口预留 | `cp/adapters/local_sandbox.py`（Docker 接口预留） |
| ④ 审计 | append-only + SHA256 hash 链 | `cp/audit/`，篡改可检测 |

### 对抗测试（护城河证明）

`cp/tests/adversarial/` 包含 8 个对抗用例，全部通过：

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

---

## 技术栈

| 层 | 技术 |
|----|------|
| 控制面 | Python 3.11+，asyncio，FastAPI + uvicorn |
| State Plane | Redis（会话/checkpoint/run 事件/消息总线），开发用 fakeredis |
| LLM | OpenAI SDK（DeepSeek 兼容）|
| 前端 | React + Vite + TypeScript |
| 审计 | append-only + SHA256 hash 链 |
| 并发 | asyncio Semaphore + 资源限额（Account）|

---

## V2 完成度与路线图

**当前（Week 6 完成，约 80%）：**
- ✅ 五平面骨架（控制面 + State Plane Redis + 执行面沙箱接口）
- ✅ 6 步统一管道 + 7 原子原语 + 4 复合操作（经 agent loop 可达）
- ✅ 四道防线（脱敏/权限/沙箱/审计 hash 链）+ 8 对抗用例
- ✅ HTTP + WebSocket API（复刻旧 gateway 契约，前端零改）
- ✅ 双总线（审计 InProcess + 消息 Redis Stream）
- ✅ Checkpoint 每步存、Scheduler 限流、HarnessRouter 适配
- ✅ Run 状态落 Redis（跨副本可观测，约束 6 在可观测面成立）

**待完成：**
- ⬜ Checkpoint **恢复续跑**（存已实现，rehydrate 恢复路径未接运行时）
- ⬜ 跨副本 **run 执行**调度（租约/工作队列）
- ⬜ AuthPort 真实现（JWT/OAuth/租户隔离）
- ⬜ `io` 原语真实 HTTP/MCP、`sub` handler 触发
- ⬜ Postgres（checkpoint/审计）、Kafka（事件回放）
- ⬜ 沙箱池生命周期管理、RemoteSandboxExecutor（沙箱经消息总线）

---

## 文档

| 文档 | 说明 |
|------|------|
| `docs/AgentOS架构设计重点关注V2.md` | **V2 架构 SSOT（当前权威）** |
| `docs/superpowers/plans/2026-07-*-python-cp-*.md` | Week 1–6 Python 控制面实现计划 |
| `docs/legacy/` | V1（Go）设计文档（历史参考，已废弃） |
| `docs/enterprise-java-design/` | 企业级 Java 设计探索（非当前实现） |

---

## Legacy（V1 Go 架构）

`kernel/`、`gateway/`、`runtime/`、`pb/` 是 AgentOS 的 **V1 实现**（Go 内核 + 网关 + gRPC 运行时）。V2 重写为 Python 控制面后，这些代码**不再开发**，保留作历史参考。

如需查阅 V1 的运行方式或设计，见 `docs/legacy/README.md`。

---

## 状态

本项目处于 **技术验证阶段**（约 80% V2 完成），尚未用于生产。欢迎交流，但请勿直接用于企业生产环境（硬隔离沙箱、完整认证等企业级能力尚未实现）。
