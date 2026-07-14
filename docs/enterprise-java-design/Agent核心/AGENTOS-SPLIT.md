# GNEX 按 AgentOS 架构拆分（定稿）

> **状态**：B 档已定稿（2026-06）— 代码按领域分包，部署 **4 个 Java 镜像** + gateway + 前端 + State Plane。  
> **范围**：模块边界、目录树、迁移映射；不涉及团队人数与 CODEOWNERS。  
> **当前执行（2026-06）**：**只做拆分**——目录重组、代码归位、`mvn compile` / 现有 E2E 不退化；**尽量不引入**新中间件、新 Adapter、新部署拓扑或业务能力（见 §1.1）。  
> **关联**：[ARCHITECTURE.md](./ARCHITECTURE.md) · [TECHNICAL-ARCHITECTURE.md](./TECHNICAL-ARCHITECTURE.md) · [Product-Spec-Distributed.md](../Product-Spec-Distributed.md)

---

## 0. 质量属性（拆分服务的目标）

> 架构的本质是**在约束下管理多维度复杂度，以服务质量属性为目标**。本节显式列出拆分决策服务的质量属性——后续所有权衡以此为准绳。

| 质量属性 | 拆分如何服务 | 验收信号 |
|---------|-----------|---------|
| **可演进性** | 模块边界清晰 + 9 阶段演进表（§9）+ `_transition/` 显式销账——任何阶段都可独立交付 | 每 Split-Phase 可独立关账；新代码不再写 `_transition/` |
| **可维护性** | 服务内高内聚 + 服务间低耦合（通过 `gnex-contracts` Port） | 单服务改动不强制其他服务发版 |
| **可部署性** | A/B/C 三档部署形态（§2）——开发单体 / 分容器 / 多副本按需选 | dev-assembler 单体启动 + B 档镜像独立部署 |
| **多租户隔离** | 所有核心表带 `tenant_id` + MyBatis-Plus 拦截器——服务拆分不破坏隔离边界 | 跨服务调用仍走租户上下文传播 |
| **可观测性** | transcript + decision_trace + agent_log 跨服务关联（[DECISION-FALLBACK §4](./DECISION-FALLBACK.md)） | 跨服务 trace 可回放 |
| **可测试性** | 服务可独立 `mvn test` + InProcess Adapter 允许单体测试 | 各服务 `mvn test` 独立通过 |

**显式非目标**（避免拆分蔓延）：

| 非目标 | 当前不服务 | 何时考虑 |
|--------|---------|---------|
| **高性能 / 低延迟** | 拆分期不优化跨服务调用延迟 | C 档多副本 + 性能压测出现瓶颈 |
| **高可用 / 故障转移** | 拆分文档定义形态，不实现 HA | Split-Phase 7 多副本 + 租约机制落地后 |
| **零停机发布** | 当前部署态允许短暂中断 | Split-Phase 7 + 滚动发布策略 |
| **安全合规** | 拆分文档不展开安全架构 | 单独安全架构文档 |

**权衡声明**：拆分优先于上述非目标——当前阶段宁可暂不优化性能/可用性，也要先把模块边界做对。这是**有意识的次优**，不是疏漏。

---

## 1. 核心原则

| 原则 | 说明 |
|------|------|
| **瘦 lib、胖 service** | 仅 `gnex-contracts` + `gnex-agent-sdk` 为共享 JAR；实现进各 `*-service` |
| **代码细、部署粗** | `user` / `project` / `skill` / `workflow` **分包**，B 档打 **一个** `platform-service` 镜像 |
| **热路径合并** | Chat / ReAct / Team / Room 进 `gnex-agent-service`（AgentOS D001） |
| **无 state-service** | State Plane = Redis + Postgres + MinIO 容器；各服务内 `persistence/` + `infra/state/` |
| **Java 包命名** | AgentOS `io/` → `controller/`；`infra/` 客户端 → `persistence/` + 可选 `infra/*` |

### 1.1 当前阶段约束（拆分优先）

**目标**：把 `_transition/` 中的代码**搬**到 `libs/*` / `services/*`，边界清晰、编译与现有行为不变。

**本阶段做 ✅**

| 项 | 说明 |
|----|------|
| 目录与模块 | `libs/`、`services/`、`_transition/`、`gnex-dev-assembler` |
| 代码搬迁 | Controller / Service / persistence 按 §5–§7 映射**剪切或复制归位** |
| 执行面拆分 | `_transition/d7-sandbox` **执行端** → `services/gnex-sandbox-runtime`；InspectorChain / 本地沙箱**客户端** → `gnex-agent-service/execution`（§9.2） |
| 包与 POM | 更新 `artifactId`、`<module>`、`dependency`；**不新增**运行时依赖 |
| 验收 | `mvn compile`；`gnex-dev-assembler` 启动；现有 Chat / 管理台 API 不退化 |

**本阶段不做 ❌**（一律后置，除非修复拆分导致的编译/启动阻断）

| 项 | 后置 Split-Phase |
|----|------------|
| Redis Stream / 独立 bus 进程 | §9 Split-Phase 3 |
| Redis 会话 + Postgres checkpoint | §9 Split-Phase 7 |
| Gateway / compose / k8s 清单 | §9 Split-Phase 7 |
| gRPC 远程 Port Adapter | 4 镜像部署时 |
| Kafka、Event Sourcing、新消息 Topic 方案 | 不采纳（§12） |
| 新 Skill / 新 Tool / 新业务能力 | 拆分关账后另开需求 |

**原则**：拆分 PR 里出现的新中间件、新配置项、新 Docker 服务 → **应拒绝或拆出**；允许的「新增」仅限：模块骨架、`gnex-contracts` 中已有映射所需的 Port 壳、以及搬迁必要的 import/POM 修正。

### 1.2 组织复杂度（Conway 定律的处理）

> 架构包括组织复杂度的管理——服务边界一旦定下，会反向塑造团队边界（Conway 定律）。本节显式承认这点，**不展开团队人数与 CODEOWNERS**（在 [TEAM-MODULE-SPLIT.md](./TEAM-MODULE-SPLIT.md) 单独管理），但声明服务边界与组织边界的关系原则。

**反向塑造的不变量**：

| 原则 | 含义 |
|------|------|
| **服务边界 = 通信边界** | 服务间调用 = 团队间协作；高频协作的子模块应放同服务内（避免跨服务调用 = 跨团队沟通） |
| **`gnex-contracts` 所有权** | Port/DTO 是服务间契约——**必须有明确 owner**（platform-service 团队或独立架构组），变更需多方评审 |
| **dev-assembler 的组织角色** | 开发单体不是部署形态，而是**团队协作形态**——所有团队在同一进程内开发，避免物理拆分造成协作壁垒 |
| **`_transition/` 的组织含义** | 迁移期双轨代码意味着**迁移期团队职责也在过渡**——明确"新代码写 services/, 旧代码只读"避免混乱 |

**服务 → 团队映射（建议，非定稿）**：

| 服务 | 建议归属 | 备注 |
|------|---------|------|
| `gnex-agent-service` | 智能引擎团队 | 热路径，核心 |
| `gnex-platform-service` | 平台 / 业务团队 | 冷路径 + 多租户 + 资源管理 |
| `gnex-bus-service` | 基础设施团队 | 消息总线 |
| `gnex-sandbox-runtime` | 安全 / 沙箱团队 | 执行面，安全敏感 |
| `gnex-dev-assembler` | 全员共建 | 开发装配，无独立 owner |
| `libs/gnex-contracts` | 架构组 / platform 团队托管 | 跨服务契约 |
| `libs/gnex-agent-sdk` | 智能引擎团队托管 | ReAct 内核 |

**与 TEAM-MODULE-SPLIT 的边界**：本表给"服务 → 团队"的高层映射；具体团队人数、CODEOWNERS、PR 评审规则在 [TEAM-MODULE-SPLIT.md](./TEAM-MODULE-SPLIT.md)。两文档关系：AGENTOS-SPLIT 定义**逻辑/物理边界**（什么是服务），TEAM-MODULE-SPLIT 定义**组织边界**（谁维护服务）。

**Conway 风险**（需主动管理）：

| 风险 | 缓解 |
|------|------|
| 团队边界固化导致接口僵化 | `gnex-contracts` 变更流程明确（RFC + 评审） |
| 跨服务协作成本高于单体重构 | dev-assembler 单体开发模式保留协作弹性 |
| 服务 owner 不清导致决策瘫痪 | 上表必须落到具体人（TEAM-MODULE-SPLIT 的 CODEOWNERS） |

---

## 2. AgentOS 五层 → GNEX

| AgentOS 层 | GNEX 落点 |
|------------|-----------|
| API Gateway | `config/deployment/gateway/` |
| 控制面（热） | `services/gnex-agent-service` |
| 控制面（冷） | `services/gnex-platform-service`（user / project / skill / workflow） |
| 执行面 | `services/gnex-sandbox-runtime` |
| Message Bus | `services/gnex-bus-service` |
| State Plane | compose 中的 Redis / Postgres / MinIO（**非** Java 服务） |
| 共享契约 | `libs/gnex-contracts` |
| Agent 内核 | `libs/gnex-agent-sdk` |

### 部署拓扑（B 档）

```text
                 gnex-gateway
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
 gnex-agent-service  gnex-platform-service  d1-web
        │              │
        └──────┬───────┘
               ▼
        gnex-bus-service ◄──► gnex-sandbox-runtime
               │
        Redis / Postgres / MinIO
```

### 部署档位

| 档位 | Java 镜像 | 适用 |
|------|-----------|------|
| **A 极简** | agent + platform + bus + sandbox | 1–3 人；bus 开发态可 InProcess |
| **B 推荐（默认）** | 同上；platform 内四域分包 | 3–8 人 |
| **C 领域全开** | user / project / skill / workflow 各独立镜像 | ≥8 人、严格 DbP |

---

## 3. 定稿目录树

> 图例：`[JAR]` 不可部署 · `[SVC]` 可独立镜像 · `[过渡]` 迁移期保留后删除

```text
gnex/
├── pom.xml
│
├── libs/
│   ├── gnex-contracts/                        # [JAR] Port、DTO、枚举（非工具类模块）
│   │   └── com/gnex/contracts/
│   │       ├── access/ runtime/ sandbox/
│   │       ├── orchestration/ registry/
│   │       ├── governance/ messagebus/ ...
│   │
│   └── gnex-agent-sdk/                        # [JAR] ReAct 内核 + Action 协议
│       └── com/gnex/agent/
│           ├── loop/ runtime/ memory/
│           ├── session/ action/ primitives/
│
├── services/
│   ├── gnex-agent-service/                    # [SVC] 热路径 · ~170 文件（d2+d4+d7+d3子集）
│   │   └── com/gnex/agent/
│   │       ├── controller/      ← AgentOS io/（Chat、SSE、Room、Team…）
│   │       ├── service/
│   │       ├── orchestration/   ← Team/Room/Orchestrator
│   │       ├── execution/       ← InspectorChain + Local/Remote Sandbox
│   │       ├── adapter/         ← 调 platform/bus 的 Port 客户端
│   │       ├── persistence/     ← agent 相关表
│   │       ├── infra/state/     ← Redis session、checkpoint
│   │       └── config/
│   │
│   ├── gnex-platform-service/                 # [SVC] 冷路径 · 四域合一
│   │   └── com/gnex/
│   │       ├── user/            ← d6-governance + d9/user
│   │       │   ├── controller/  # Auth、User、Audit、Sso、Billing
│   │       │   ├── auth/ audit/ billing/
│   │       │   └── persistence/
│   │       ├── project/         ← d9/project（~6 文件）
│   │       │   ├── controller/ service/ persistence/
│   │       ├── skill/           ← d5-registry
│   │       │   ├── controller/ registry/ credential/
│   │       │   └── persistence/ infra/storage/
│   │       ├── workflow/        ← d3/workflow
│   │       │   ├── controller/ orchestration/ persistence/
│   │       └── config/
│   │
│   ├── gnex-bus-service/                      # [SVC] · d8-bus ~9 文件
│   │   └── com/gnex/bus/ bus/ persistence/ config/
│   │
│   └── gnex-sandbox-runtime/                  # [SVC] 执行面
│       └── com/gnex/sandbox/ consumer/ executor/ producer/ config/
│
├── gnex-dev-assembler/                        # 开发单体（AgentOS D004）
├── d1-web/frontend/
├── config/agents/ + config/deployment/        # compose、gateway、k8s
│
└── _transition/                               # [过渡] d2~d9，迁移完成后删除
```

### 目标 `pom.xml` modules（B 档）

```xml
<modules>
  <module>libs/gnex-contracts</module>
  <module>libs/gnex-agent-sdk</module>
  <module>services/gnex-agent-service</module>
  <module>services/gnex-platform-service</module>
  <module>services/gnex-bus-service</module>
  <module>services/gnex-sandbox-runtime</module>
  <module>gnex-dev-assembler</module>
  <module>d1-web</module>
</modules>
```

---

## 4. `gnex-contracts` 是什么

**跨服务契约（AgentOS `shared/`）**，不是常量/工具类包。

| 放 ✅ | 不放 ❌ |
|------|--------|
| Port 接口（~60%） | `@Service` 业务实现 |
| DTO / Record（~30%） | MyBatis entity/mapper |
| 领域枚举、契约异常 | 工具类、ReAct 循环 |
| `ApiResponse` 等极少外壳 | Spring 配置 |

```text
gnex-contracts  →  说什么（接口 + 数据结构）
gnex-agent-sdk  →  怎么做（ReAct 引擎）
*-service       →  装配 + HTTP + persistence 实现
```

---

## 5. `infra` 在哪里

| 概念 | 落点 |
|------|------|
| **State Plane**（Redis/PG/MinIO 容器） | `config/deployment/docker-compose` |
| **AgentOS `infra/`**（Java 客户端 + Repository） | 各 `*-service` 的 `persistence/`、`config/`、可选 `infra/{state,storage,migration}` |

按表拆 `d9-platform`：

| 原域 | 迁入 |
|------|------|
| `agent/*` | `gnex-agent-service` |
| `user/*` `audit/*` | `platform-service/user` |
| `project/*` | `platform-service/project` |
| `skill/*` `credential/*` | `platform-service/skill` |
| `workflow/*` | `platform-service/workflow` |
| 总线持久化 | `gnex-bus-service` |

---

## 6. 现有模块 → 去向

| 现有模块 | 去向 |
|----------|------|
| `gnex-contracts` | 保留 `libs/` |
| `d4-runtime` | → `gnex-agent-sdk` + agent-service 胶水；**删除 d4 模块** |
| `d2-access` | **解散** → 各 service 的 `controller/` |
| `d3-orchestration` | Team/Room → agent-service；Workflow → platform/workflow |
| `d5-registry` | → platform/skill |
| `d6-governance` | → platform/user |
| `d7-sandbox` | 客户端 → agent-service/execution；执行端 → sandbox-runtime |
| `d8-bus` | → bus-service |
| `d9-platform` | **按表拆分**到各 service `persistence/` |
| `gnex-assembler` | → `gnex-dev-assembler` |

### 模块 Java 文件数（现状）

| 模块 | 文件数 |
|------|--------|
| d2-access | 48 |
| d3-orchestration | 71 |
| d4-runtime | 123 |
| d5-registry | 39 |
| d6-governance | 50 |
| d7-sandbox | 33 |
| d8-bus | 9 |
| d9-platform | 109 |

---

## 7. AgentOS 包 → Java 包对照

| AgentOS | Java 落点 |
|---------|-----------|
| `shared/` | `libs/gnex-contracts` |
| `core/` | `libs/gnex-agent-sdk` |
| `io/` | 各 service 的 `controller/` |
| `orchestration/` | agent-service / platform/workflow 的 `orchestration/` |
| `auth/` `audit/` | platform-service/user |
| `execution/` | agent-service/execution + contracts 中的 Port |
| `infra/` | 各 service `persistence/` + `infra/*` |
| `sandbox-runtime/` | `gnex-sandbox-runtime` |

---

## 8. 开发态 vs 部署态

| Port | 开发（dev-assembler） | 部署 |
|------|----------------------|------|
| `SandboxPort` | LocalSandboxExecutor | Remote → bus → sandbox-runtime |
| `MessageBusPort` | InProcess 或 **database**（SQLite 队列表，**默认**） | 独立 bus-service → **Redis Stream**（跨进程） |
| `AuthPort` / Skill / Workflow | InProcess | gRPC → platform-service |
| `StatePort` | SQLite | Redis + Postgres |

业务代码不变；Spring Profile / `gnex.message-bus.mode` 切换 Adapter。

> **Redis Stream 不是开发前提。** 单体 `gnex-dev-assembler` 下 Chat、管理台、Agent 协作均可跑通，**无需 Redis**。Redis Stream 仅在 agent / sandbox **分进程部署**时作为跨 JVM 的 Action/Observation 通道；配置项见 `_transition/d8-bus` 的 `MessageBusProperties`（`mode`: `database` \| `redis`）。

---

## 9. 演进顺序

> **当前聚焦**：Split-Phase **4–6**（代码迁入 `services/*`，含 sandbox 执行面；dev-assembler 仍可单体启动）。Split-Phase **3 / 7** 属中间件与部署，**不在当前拆分阶段**（见 §1.1、§9.1）。

| 阶段 | 内容 | 验收 | 状态 | 当前阶段 |
|------|------|------|:----:|:--------:|
| 1 | contracts 补 SandboxPort / StatePort / Action·Observation | `mvn compile` | ✅ | ✅ 已完成 |
| 2 | 抽出 `gnex-agent-sdk`；建 service 骨架 | 模块可编译 | ✅ | ✅ 已完成 |
| 3 | `gnex-bus-service` + Redis Stream | 跨进程 pub/sub | ☐ | **不做** |
| 4 | `gnex-agent-service` + dev-assembler | Chat E2E | ☐ | **进行中** |
| 5 | `gnex-platform-service`（从 d2/d5/d6/d9 迁 controller + persistence） | 管理台 API | ☐ | **进行中** |
| 6 | `gnex-sandbox-runtime`（从 d7 迁 execution 端；agent-service 留客户端） | 本地沙箱执行不退化 | ☐ | **进行中** |
| 7 | Session → Redis；checkpoint → Postgres；Gateway | 多副本 agent | ☐ | **不做** |

### 9.1 Split-Phase 3 与 Redis Stream（当前阶段跳过）

**结论：Split-Phase 3 不是功能上线的前置条件；当前拆分阶段明确跳过。**

| 场景 | 总线实现 | 是否需要 Redis |
|------|----------|:--------------:|
| `gnex-dev-assembler` 单体开发 | InProcess / **database**（默认） | **否** |
| 4 Java 镜像、agent ↔ sandbox 分进程 | 独立 `gnex-bus-service` + Redis Stream | **是** |

**为何文档仍保留 Split-Phase 3？** B 档目标是把控制面与沙箱拆成不同容器；进程间无法共享 InProcess 或单机 SQLite 队列，需要 Redis Stream 作 Action/Observation 的共享通道。GNEX 定 Redis Stream，**不用 Kafka**（见 §12 #8）。

**推荐迁移路径（当前执行）：**

```text
Split-Phase 1–2 ✅
    → Split-Phase 4–6（代码搬迁：agent / platform / sandbox 执行面 + dev-assembler 单体验收）
    → 拆分关账后，再按需启动 Split-Phase 3 / 7（Redis bus、状态外化、Gateway）
```

### 9.2 Split-Phase 6 与执行面拆分（当前阶段范围内）

**结论：Split-Phase 6 是代码拆分，不是新中间件。** 与 Split-Phase 3（Redis Stream）不同，Split-Phase 6 **在当前拆分阶段执行**。

| 来源（`_transition`） | 去向（`services/*`） |
|------------------------|----------------------|
| `d7-sandbox` 执行端（`SandboxExecutor`、ProcessTool worker 等） | `gnex-sandbox-runtime` |
| `d7-sandbox` 客户端（`InspectorChain`、`boundary/*`） | `gnex-agent-service/execution` |

**开发态**：dev-assembler 仍可通过 `SandboxPort` → **LocalSandboxExecutor** 单体跑通，**无需**独立起 sandbox 容器或 Redis Topic。

**部署态**（Split-Phase 3 之后）：agent-service 经 bus 将 `ActionMessage` 发往 sandbox-runtime，再收 `ObservationMessage`——那是 **Split-Phase 3 + 独立镜像** 的事，不是 Split-Phase 6 拆分的前置条件。

Split-Phase 6 验收：`mvn compile`；现有 ProcessTool / InspectorChain 行为与拆分前一致。

---

## 10. 关键结论

1. **B 档 = 4 Java 镜像**：agent、platform、bus、sandbox；不必为 project 单独起服务。
2. **独立开发靠包边界 + contracts**，不靠 6 个 Docker 镜像。
3. **无 `gnex-state-service`**；**`gnex-contracts` 不是工具库**。
4. **C 档**时把 platform 下四子目录拆成独立 `*-service` 即可，Port 契约不变。
5. 迁移期 `_transition/` 保留 d2–d9；**新代码只写 `libs/*` 与 `services/*`**。
6. **Redis Stream 仅用于跨进程 bus**；dev-assembler 默认 `database` 总线，**不接 Redis 也能完整开发**（Split-Phase 3 当前跳过，见 §9.1）。
7. **当前阶段 = 拆分 only**（§1.1）：Split-Phase **4–6** 代码搬迁；不引入 Redis / Gateway / gRPC 远程 Adapter / 新业务能力；验收标准是编译 + 现有 E2E 不退化。

---

## 11. 维护约定

- 部署档位或目录树变更 → 更新本文 §2–§3
- 新增 Port → `gnex-contracts` + 本文 §4（**仅限拆分映射所需**，见 §1.1）
- Split-Phase 关账 → 同步 [ARCHITECTURE.md](./ARCHITECTURE.md) 演进表
- 外部 AgentOS 基线文档评审结论 → 更新本文 §12
- **拆分 PR 审查**：是否只做搬迁/边界调整？是否夹带中间件或新功能？若是 → 退回或拆 PR

---

## 12. AgentOS 基线评审决策表（一页）

> **来源**：《AgentOS架构设计重点关注1.md》v1.0（2026-06-15/16）团队评审对照。  
> **SSOT 优先级**：本文 > [Product-Spec-Distributed.md](../Product-Spec-Distributed.md) > 外部基线文档。  
> **图例**：✅ 保留 · ✏️ 改写 · ❌ 不采纳 · ⚠️ POC 后定

| # | 基线条目 | 决策 | 负责域 | Split-Phase | GNEX 落点 / 备注 |
|---|----------|:----:|--------|:-----:|------------------|
| **基础设施（§1–17）** |
| 1 | D001 控制面模块化单体 | ✅ | agent + platform | §9-4~5 | 热/冷分包；B 档 2 镜像 |
| 2 | D002 执行面独立 | ✅ | sandbox | §9-6 | `gnex-sandbox-runtime`；客户端在 agent-service |
| 3 | D003 状态外化 | ✏️ | 各 service | §9-7 | SQLite（dev）→ Redis + Postgres；**不用 Kafka 作状态真相源** |
| 4 | D004 Port 解耦开发/部署 | ✅ | contracts | §9-1~2 | `gnex-contracts` + Profile 切 Adapter |
| 5 | D005 Gateway 只管外部入口 | ✅ | deployment | §9-7 | `config/deployment/gateway/` |
| 6 | D006 总线为控制面↔沙箱唯一通道 | ✏️ | bus + sandbox | §9-3,6 | Agent 通信用 Redis Stream；**不用** `actions.{sandbox_id}` 万 Topic |
| 7 | D007 Agent YAML 配置池 | ✏️ | platform/skill | C 档 | 保留 DB + Skill Registry；YAML 仅作可选导入 |
| 8 | D008 生产消息总线用 Kafka | ❌ | bus | — | GNEX 定 **Redis Stream**（见 Product-Spec-Distributed） |
| 9 | Event Sourcing + CQRS 全量 | ❌ | — | — | 用 `react_checkpoint` + `agent_run_event`，非 ES 回放 |
| 10 | 沙箱 OS 级容器池 + Registry | ✏️ | sandbox | §9-6 | 现状 ProcessBuilder；容器池为 sandbox-runtime 目标 |
| 11 | 每步 checkpoint 默认 | ✏️ | agent-sdk | §9-7 | 已有 checkpoint；策略可配置，非强制 every_step |
| 12 | 1 万 Agent 容量目标 | ✏️ | 全栈 | C 档+ | 远期目标；先验收 §9 阶段 7 多副本 |
| 13 | Python `agent-os/` 示例树 | ❌ | — | — | 仅思想参考；实现 SSOT 为本文 §3 Java 目录 |
| 14 | 阶段 1→3「代码零改动」 | ✏️ | 各 service | §9 | Adapter 层零改动；infra 切换需改配置与连接池 |
| **Harness / 原语层（§18–27）** |
| 15 | D009 路线 C：原语蒸馏编译 | ⚠️ | agent-sdk | POC | 不做「三框架齐蒸馏」；单框架工具映射 POC 可选 |
| 16 | 7 原子原语 + 4 复合操作 | ❌ | — | — | GNEX 用 Spring AI Tool + `HarnessRuntime`，非 7 原语 API |
| 17 | read/write URL scheme | ❌ | — | — | 存储路由留在 Tool/Port 层，不暴露给 LLM |
| 18 | LLM 动态映射 GNEX 原语（D018） | ❌ | — | — | LLM 调具名 Tool；InspectorChain 拦截 |
| 19 | Harness Profile 仅 YAML（D016） | ✏️ | skill | C 档 | `.claude/skills` + Skill Registry 为主 |
| 20 | 映射表 `*_mapping.yaml`（§26） | ❌ | — | — | 与 D016 矛盾；不维护静态映射表 |
| 21 | Harness Router 多风格副本 | ⚠️ | orchestration | C 档 | Orchestrator 路由保留；多镜像风格副本远期 |
| 22 | 「任意 Harness 实例副本运行」 | ❌ | — | — | 改为 Skill + MCP + 安全层集成，非黑盒/半黑盒加载 |
| 23 | 三层嵌套 ReAct（§27） | ✏️ | agent-sdk | — | 概念对齐 ReAct + Sub-Agent；无独立「复合操作脚本层」 |
| 24 | 平台安全 ⊃ Harness 安全 | ✅ | sandbox + governance | 已落地 | `InspectorChain` + `project.constraints_json` |
| 25 | MCP 桥接（路线 B）过渡 | ✅ | runtime | 已落地 | `MCPExecutor`；企业可控性的短期可行路径 |

### 12.1 决策统计

| 决策 | 数量 |
|------|:----:|
| ✅ 保留 | 8 |
| ✏️ 改写 | 9 |
| ⚠️ POC 后定 | 2 |
| ❌ 不采纳 | 6 |

### 12.2 文档收敛（已生效）

| 原文档 | 处置 |
|--------|------|
| §1–17 基础设施 | 吸收进本文 + Product-Spec-Distributed；删 Kafka ES、Python 树、万 Topic |
| §18–27 Harness 原语 | **不**作为实现 SSOT；能力对照 [HARNESS-MATURITY.md](./HARNESS-MATURITY.md) |
| 附录 B 决策 D001–D008 | D001–D005、D007 对齐；**D008 以 Redis Stream 为准** |
| 附录 B 决策 D009–D018 | 仅 D010/D014 思想保留；**D011–D013、D016–D018 不采纳** |

### 12.3 MVP 路线（评审共识）

```text
当前：拆分 only（Split-Phase 4–6，§1.1）— dev-assembler + LocalSandbox / database 总线
后续：Redis bus + 状态外化 + Gateway（Split-Phase 3 / 7，拆分关账后再做）
Harness：Skill Registry + MCP + InspectorChain（已运行，拆分期不扩展）
        路线 C 仅限 Claude Code 工具面 POC，不阻塞拆分
```
