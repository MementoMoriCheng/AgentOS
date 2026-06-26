# GNEX 按 AgentOS 架构拆分（定稿）

> **状态**：B 档已定稿（2026-06）— 代码按领域分包，部署 **4 个 Java 镜像** + gateway + 前端 + State Plane。  
> **范围**：模块边界、目录树、迁移映射；不涉及团队人数与 CODEOWNERS。  
> **关联**：[ARCHITECTURE.md](./ARCHITECTURE.md) · [TECHNICAL-ARCHITECTURE.md](./TECHNICAL-ARCHITECTURE.md) · [Product-Spec-Distributed.md](../Product-Spec-Distributed.md)

---

## 1. 核心原则

| 原则 | 说明 |
|------|------|
| **从大到小** | 拆分粒度由粗到细：先分层骨架（`libs/` + `services/`），再跨服务契约（contracts 接口），再内核 JAR + service 空壳，最后服务内部 infra。代码细、部署粗——开发单体（`dev-assembler`，零网络开销），部署微服务，靠接口解耦（D004）。瘦 lib（仅 `gnex-contracts` + `gnex-agent-sdk` 共享 JAR）、胖 service（Controller / persistence / 装配进各 `*-service`）。 |
| **面向未来架构** | 当前 <500 agent，架构预留伸缩到 1 万+：②控制面（`gnex-agent-service`）无状态可水平扩展；执行面（sandbox）独立伸缩、可丢弃重建；按 A/B/C 三档渐进，包边界先行、部署按需。 |
| **状态持久化** | State Plane = Redis + Postgres + MinIO 容器（非 Java 服务）；各服务内 `persistence/` + `infra/state/` 直接读写状态面；控制面无状态，可多副本。 |

> **Java 包命名约定**：AgentOS `io/` 对应 `controller/`；`infra/` 客户端对应 `persistence/` + 可选 `infra/*`。

---

## 2. 架构总览：五层 + 共享层 → GNEX 落点

> 编号 ①–⑤ 对应整体架构的五层。
> **关键澄清（务必先读）**：
> - ② 控制面（无状态、多副本水平扩展）= **`gnex-agent-service`**，可按负载起多个副本（#1/#2/#N）。
> - `gnex-platform-service` **不属于控制面**。它是单实例的管理服务（user / skill / workflow / project / auth / audit），**被控制面通过接口调用**——无论控制面扩到几个副本，始终只对应一个 platform。

### 2.1 五层架构

| 架构层 | GNEX 落点 | 说明 |
|--------|-----------|------|
| ① API Gateway | `config/deployment/gateway/` | 纯外部入口，不参与调度 |
| ② 控制面（模块化单体，可多副本） | `gnex-agent-service`（水平扩展） | Agent Loop / 编排 / IO，无状态 |
| ③ State Plane | compose：Redis / Postgres / MinIO | 非 Java 服务 |
| ④ Message Bus | `gnex-bus-service` | 控制面↔沙箱唯一通道 |
| ⑤ 执行面 | `gnex-sandbox-runtime` | 沙箱计算单元 |

### 2.2 共享层

| 架构层 | GNEX 落点 | 说明 |
|--------|-----------|------|
| 契约层 | `libs/gnex-contracts` | 接口 / DTO / 枚举 |
| Agent 内核（SDK） | `libs/gnex-agent-sdk` | ReAct 引擎 + Action 协议 |

### 2.3 平台管理服务（独立于五层，GNEX 特有）

> `gnex-platform-service` **不属于控制面**。它承载治理与管理域，**单实例**部署，被控制面（agent-service）通过接口调用。

| 服务 | 承载域 | 副本 |
|------|--------|------|
| `gnex-platform-service` | user / project / skill / workflow（含 auth / audit / billing / credential） | 单实例 |

### 2.4 部署拓扑

```text
                         ① gnex-gateway
                               │
          ┌────────────────────┼──────────────────────┐
          ▼                    ▼                      ▼
  ┌───────────────────┐  ┌──────────────┐     d1-web（前端）
  │ ② 控制面（多副本）  │  │gnex-platform │
  │  无状态·水平扩展   │  │  （单实例）   │
  │ ┌──────┐ ┌──────┐ │  │ user / skill │
  │ │agent │ │agent │ │◄►│ workflow /   │  ← platform 不属于控制面，
  │ │svc#1 │ │svc#2 │…│  │ project /    │    被控制面调用；无论 agent
  │ └──────┘ └──────┘ │  │ auth / audit │    几个副本，platform 只有一个
  └────────┬──────────┘  └──────┬───────┘
           ▼                    │
         ④ gnex-bus-service     │
              │                 │
              ▼                 │
  ⑤ gnex-sandbox-runtime        │    ← ⑤执行面 只与 ④Message Bus 通信，
  （只消费 ④ 的 Action，回传     │       不直接连控制面、不直接连状态面
   Observation）                │
                                ▼
                  ③ Redis / Postgres / MinIO
```

---

## 3. 定稿目录树

> 图例：`[JAR]` 不可部署 · `[SVC]` 可独立镜像 · `[过渡]` 迁移期保留后删除

```text
gnex/
├── pom.xml
│
├── libs/
│   ├── gnex-contracts/                        # [JAR] 接口、DTO、枚举（非工具类模块）
│   │   └── com/gnex/contracts/
│   │       ├── access/
│   │       ├── runtime/
│   │       ├── sandbox/
│   │       ├── orchestration/
│   │       ├── registry/
│   │       ├── governance/
│   │       └── messagebus/
│   │
│   └── gnex-agent-sdk/                        # [JAR] ReAct 内核 + Action 协议
│       └── com/gnex/agent/
│           ├── loop/
│           ├── runtime/
│           ├── memory/
│           ├── session/
│           ├── action/
│           └── primitives/
│
├── services/
│   ├── gnex-agent-service/                    # [SVC] ②控制面·运行核心 ~170 文件（Chat/ReAct/Team/Room/Inspector）
│   │   └── com/gnex/agent/
│   │       ├── controller/      ← Chat、SSE、Room、Team…
│   │       ├── service/
│   │       ├── orchestration/   ← Team/Room/Orchestrator
│   │       ├── execution/       ← InspectorChain + Local/Remote Sandbox
│   │       ├── adapter/         ← 调 platform/bus 的接口客户端
│   │       ├── persistence/     ← agent 相关表
│   │       ├── infra/state/     ← Redis session、checkpoint
│   │       └── config/
│   │
│   ├── gnex-platform-service/                 # [SVC] 平台管理服务·单实例（user/project/skill/workflow，不属于控制面）
│   │   └── com/gnex/
│   │       ├── user/            ← d6-governance + d9/user
│   │       │   ├── controller/  # Auth、User、Audit、Sso、Billing
│   │       │   ├── auth/
│   │       │   ├── audit/
│   │       │   ├── billing/
│   │       │   └── persistence/
│   │       ├── project/         ← d9/project（~6 文件）
│   │       │   ├── controller/
│   │       │   ├── service/
│   │       │   └── persistence/
│   │       ├── skill/           ← d5-registry
│   │       │   ├── controller/
│   │       │   ├── registry/
│   │       │   ├── credential/
│   │       │   ├── persistence/
│   │       │   └── infra/storage/
│   │       ├── workflow/        ← d3/workflow
│   │       │   ├── controller/
│   │       │   ├── orchestration/
│   │       │   └── persistence/
│   │       └── config/
│   │
│   ├── gnex-bus-service/                      # [SVC] · d8-bus ~9 文件
│   │   └── com/gnex/bus/
│   │       ├── bus/
│   │       ├── persistence/
│   │       └── config/
│   │
│   └── gnex-sandbox-runtime/                  # [SVC] 执行面
│       └── com/gnex/sandbox/
│           ├── consumer/
│           ├── executor/
│           ├── producer/
│           └── config/
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
| 接口定义（~60%） | `@Service` 业务实现 |
| DTO / Record（~30%） | MyBatis entity/mapper |
| 领域枚举、契约异常 | 工具类、ReAct 循环 |
| `ApiResponse` 等极少外壳 | Spring 配置 |

```text
gnex-contracts  →  说什么（接口 + 数据结构）
gnex-agent-sdk  →  怎么做（ReAct 引擎）
*-service       →  装配 + HTTP + persistence 实现
```

---

## 5. 按表拆 `d9-platform`

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

## 6. 现状基准与模块去向

### 6.1 现状 vs 目标（起点基准）

| 维度 | 现状 | 目标 |
|------|------|------|
| Maven 模块 | `d2`–`d9` + `gnex-contracts` + `gnex-core` + `gnex-assembler` | `libs/*` + `services/*` + `gnex-dev-assembler` |
| 目录 | 无 `services/`、`libs/` | 见 §3 定稿目录树 |
| 共享 JAR | 仅 `gnex-contracts`（145 文件） | + `gnex-agent-sdk`（从 d4 抽 ReAct 内核） |
| 接口缺口 | 无 `SandboxPort` / `StatePort` | contracts 补全 + Profile 切 Adapter |
| 部署 | 单体 `gnex-assembler`（8080） | 4 镜像 + compose；开发仍用 dev-assembler |
| 消息总线 | d8-bus（9 文件，同进程） | 独立 `gnex-bus-service` + Redis Stream（非 Kafka） |
| 状态 | SQLite 单机 | dev=SQLite；prod=Redis（session）+ Postgres（checkpoint） |

### 6.2 现有模块规模与去向

| 源模块 | 文件数 | 去向 |
|--------|--------|------|
| gnex-contracts | 145 | `libs/gnex-contracts`（保留，共享 JAR） |
| d4-runtime | 123 | `gnex-agent-sdk` + agent-service 胶水（删除 d4 模块） |
| d9-platform | 109 | 按域拆入各 service 的 `persistence/`（agent / platform / bus） |
| gnex-core | 103 | 按域并入 agent / platform（skill / workspace 等） |
| d3-orchestration | 71 | Team/Room 并入 agent-service；Workflow 并入 platform/workflow |
| d6-governance | 50 | platform/user |
| d2-access | 48 | 解散，并入各 service 的 `controller/` |
| d5-registry | 39 | platform/skill |
| d7-sandbox | 33 | 客户端并入 agent-service/execution；执行端并入 sandbox-runtime |
| d8-bus | 9 | bus-service |
| gnex-assembler | — | `gnex-dev-assembler` |

---

## 7. AgentOS 包 → Java 包对照

| AgentOS | Java 落点 |
|---------|-----------|
| `shared/` | `libs/gnex-contracts` |
| `core/` | `libs/gnex-agent-sdk` |
| `io/` | 各 service 的 `controller/` |
| `orchestration/` | agent-service / platform/workflow 的 `orchestration/` |
| `auth/` `audit/` | platform-service/user |
| `execution/` | agent-service/execution + contracts 中的接口 |
| `infra/` | 各 service `persistence/` + `infra/*` |
| `sandbox-runtime/` | `gnex-sandbox-runtime` |

---

## 9. 拆分顺序（由大到小原则）

### 9.0 总览

按照第一版拆分经验，按照以下步骤拆分较为合理。

> **由大到小**：拆分粒度逐级递减——先定**分层骨架**（`libs/` / `services/` / `_transition/`，Phase 0）→ 再定**跨服务边界**（contracts 接口，Phase 1）→ 抽**内核 JAR + service 空壳**（Phase 2）→ 逐个**服务独立**（bus → agent → platform → sandbox，Phase 3–6）→ 最后细化**服务内部 infra**（状态外化、多副本，Phase 7）。先粗后细，每一步都可独立编译验证。

| 阶段 | 目标 | 验收 |
|------|------|------|
| Phase 0 | 骨架准备：搭 libs/services/_transition、双轨编译 | 新旧模块并存，`mvn compile` 绿 |
| Phase 1 | 契约层：先定"说什么" | contracts 编译通过，接口评审关账 |
| Phase 2 | 抽 agent-sdk + service 骨架 | 7 个新 module 可编译 |
| Phase 3 | 消息总线独立 | 两进程 pub/sub 通 |
| Phase 4 | agent-service + Chat E2E | dev-assembler Chat 全链路通 |
| Phase 5 | platform-service 四域合一 | 管理台 CRUD 全绿 |
| Phase 6 | sandbox-runtime 执行面 | 三容器联调，Remote tool call 通 |
| Phase 7 | 状态外化 + Gateway + 多副本 | 双 agent 副本无会话丢失 |

> **并行策略**：Phase 4（agent 控制面）与 Phase 5（platform 管理面）可由两人并行；Phase 3（bus）可与 Phase 2 尾部重叠。

### Phase 0 — 骨架准备（先做）

| 任务 | 内容 | 产出 |
|------|------|------|
| 0.1 | 创建 `libs/`、`services/`、`_transition/` 骨架 | 空模块可 `mvn compile` |
| 0.2 | 根 `pom.xml` 增加目标 modules（旧模块暂保留） | 双轨编译通过 |
| 0.3 | 编写 `_transition/README.md`：禁止新功能进 d2–d9 | 协作约定 |
| 0.4 | 更新 `CLAUDE.md` / CI 指向新路径 | 文档一致 |

**验收**：新旧模块并存，`mvn compile` 绿。

### Phase 1 — 契约层（§9-1）

目标：跨服务边界先定"说什么"，再动代码。

| 任务 | 内容 |
|------|------|
| 1.1 | 在 `gnex-contracts` 新增 `SandboxPort`（Local/Remote 抽象）、`StatePort`（session/checkpoint） |
| 1.2 | 补 Action / Observation 协议 DTO（agent ↔ sandbox 经 bus） |
| 1.3 | 梳理现有接口：`MessageBusPort`、`AuthPort`、`AuditPort`、Skill/Workflow 相关 — 标注 `@Deprecated` 或拆 REST 接口 vs 内部接口 |
| 1.4 | 明确 contracts 边界：只放接口/DTO/枚举，不放 `@Service`、Mapper、工具类 |

**验收**：`mvn -pl libs/gnex-contracts compile` 通过；接口评审关账。

### Phase 2 — 抽出 agent-sdk + service 骨架（§9-2）

目标：ReAct 内核独立 JAR，四个 service 空壳可编译。

| 任务 | 从 → 到 |
|------|---------|
| 2.1 | 建 `libs/gnex-agent-sdk`：`ReActLoop`、`AgentRuntime`、`SessionManager`、memory/hooks、checkpoint 逻辑 |
| 2.2 | 建 `services/gnex-agent-service` 骨架：`controller/`、`service/`、`config/` |
| 2.3 | 建 `services/gnex-platform-service`：`user/`、`project/`、`skill/`、`workflow/` 四包 |
| 2.4 | 建 `services/gnex-bus-service`、`services/gnex-sandbox-runtime` 骨架 |
| 2.5 | `gnex-assembler` → `gnex-dev-assembler`：依赖全部 service，Profile=`dev` 时 InProcess Adapter |
| 2.6 | d4-runtime 标记废弃，代码 copy/move 到 sdk + agent-service（非一次性 delete） |

**验收**：7 个新 module 均可编译；dev-assembler 仍能单体启动（功能可暂不全）。

### Phase 3 — 消息总线独立（§9-3）

目标：控制面 ↔ 执行面异步边界落地。

| 任务 | 内容 |
|------|------|
| 3.1 | 迁移 d8-bus → `gnex-bus-service`（`bus/`、`persistence/`、`config/`） |
| 3.2 | 实现 Redis Stream 后端（替换/并行 InProcess） |
| 3.3 | 定义 Topic：`actions.{sandbox_id}`、`observations.{sandbox_id}`（不用万 Topic Kafka 方案） |
| 3.4 | bus HTTP 门面：从 d2 `AgentMessageBusController` 迁入 bus-service 或经 gateway 路由 |
| 3.5 | dev-assembler：`MessageBusPort` → InProcess；独立部署 → gRPC/HTTP → bus-service |

**验收**：两进程 agent + bus 间 pub/sub 通；单元/集成测试覆盖 publish/consume/dead-letter。

### Phase 4 — agent-service + dev-assembler Chat E2E（§9-4）

目标：控制面核心聚合，Chat 全链路在新结构跑通。

迁移映射：

| 源 | 去向 |
|----|------|
| d2-access | Chat/SSE/Room/Team/Shell 并入 `agent-service/controller/` |
| d3 子集 | Team、Room、Orchestrator 并入 `agent-service/orchestration/` |
| d4 剩余 | 胶水、SSE、Adapter 并入 `agent-service/service/` + `adapter/` |
| d7 客户端 | InspectorChain、LocalSandboxExecutor 并入 `agent-service/execution/` |
| d9 `agent/*` | 并入 `agent-service/persistence/` |

| 任务 | 内容 |
|------|------|
| 4.1 | `ReActLoop` 依赖 `SandboxPort`（dev=Local，prod=Remote→bus） |
| 4.2 | Platform 调用：`adapter/` 实现 Skill/Auth 等接口客户端（dev=InProcess） |
| 4.3 | Session 仍 SQLite（本阶段不迁 Redis） |
| 4.4 | dev-assembler E2E：前端 Chat → SSE 完整回合 |

**验收**：`mvn -pl gnex-dev-assembler spring-boot:run` + 前端 Chat E2E；`d2-access` 中 agent 相关 Controller 已迁空或删。

### Phase 5 — platform-service 管理面（§9-5）

目标：管理台 API 四域合一，一个镜像。

| 域 | 源模块 | 目标包 |
|----|--------|--------|
| user | d6-governance + d9/user + d2 governance controllers | `platform/user/`（auth、audit、billing） |
| project | d9/project + d2 ProjectController | `platform/project/` |
| skill | d5-registry + gnex-core/skill + d2 registry controllers | `platform/skill/` |
| workflow | d3/workflow + d2 WorkflowController | `platform/workflow/` |

| 任务 | 内容 |
|------|------|
| 5.1 | 按表拆分 d9-platform persistence 到四域 `persistence/` |
| 5.2 | Credential、Skill Registry、MCP 注册进 `skill/` |
| 5.3 | dev-assembler：Auth/Skill/Workflow 接口 → InProcess 或 HTTP 调 platform |
| 5.4 | 前端管理页回归（Agent/Skill/Workflow/User/Project） |

**验收**：platform-service 独立 jar 可启；管理台 CRUD 全绿；d5/d6 中已迁代码标记废弃。

### Phase 6 — sandbox-runtime 执行面（§9-6）

目标：工具执行与 Agent 进程隔离。

| 任务 | 内容 |
|------|------|
| 6.1 | 迁移 d7 执行端 → `gnex-sandbox-runtime`（consumer/executor/producer） |
| 6.2 | `RemoteSandboxExecutor`（agent-service）经 bus 发 Action、收 Observation |
| 6.3 | InspectorChain 留在 agent-service；实际 bash/文件 IO 在 sandbox 容器 |
| 6.4 | Dockerfile + compose 服务定义 |
| 6.5 | 现状 ProcessBuilder 作 fallback；容器池为远期目标 |

**验收**：agent + bus + sandbox 三容器联调；Remote 模式跑通一次 tool call。

### Phase 7 — 状态外化 + Gateway + 多副本（§9-7）

目标：生产拓扑完整，agent 可水平扩展。

| 任务 | 内容 |
|------|------|
| 7.1 | Session 热状态 → Redis（`agent-service/infra/state/`） |
| 7.2 | checkpoint → Postgres（非 Event Sourcing 全量回放） |
| 7.3 | MinIO 产物/Skill 包存储（`platform/skill/infra/storage/`） |
| 7.4 | `config/deployment/gateway/`：路由 `/api/chat` → agent，`/api/admin/*` → platform |
| 7.5 | `config/deployment/docker-compose.yml`：4 Java + Redis + PG + MinIO + gateway |
| 7.6 | agent-service 双副本 + 共享 Redis session 验证 |
| 7.7 | 删除 `_transition/` 下 d2–d9；根 pom 只保留目标 modules |

**验收**：compose 全栈起；双 agent 副本 Chat 无会话丢失；`mvn clean package` 仅含 libs + services + dev-assembler。

### 风险与约束

| 风险 | 应对 |
|------|------|
| 大爆炸迁移 | 双轨 + `_transition/`；按 Phase 4/5 先 E2E 再删旧模块 |
| gnex-core 与 d4/d5 重叠 | Phase 2 先 inventory 清单，避免重复迁入 |
| contracts 膨胀成工具库 | Code Review 卡 §4 边界；MyBatis entity 不进 contracts |
| 前端 API 路径变化 | Gateway 统一前缀；或 Phase 7 前保持 dev-assembler 单端口 |
| 测试/装配代码 240 文件在 assembler | 测试 fixture 随 service 拆或留 dev-assembler |

> 明确不采纳：Kafka 作总线、Event Sourcing 全量、独立 state-service、Python agent-os 目录树、7 原子原语 API。

### 每阶段关账检查清单

- `mvn compile` / `mvn test` 绿
- 新代码未进入 `_transition/` 以外旧模块
- 新增接口已更新本文 §4
- dev-assembler 仍可本地一键启动
- 本阶段验收 E2E 用例通过
- Phase 7 后同步 `ARCHITECTURE.md` 演进表

### 下一步建议

若开始实施，建议从 **Phase 0 + Phase 1** 动手：先搭 `libs/` / `services/` 骨架并补 `SandboxPort` / `StatePort`，不动业务逻辑，风险最低。

---

## 10. 关键结论

1. **B 档 = 4 Java 镜像**：agent（②控制面，可多副本）、platform（管理面，单实例）、bus、sandbox；不必为 project 单独起服务。
2. **独立开发靠包边界 + contracts**，不靠 6 个 Docker 镜像。
3. **无 `gnex-state-service`**；**`gnex-contracts` 不是工具库**。
4. **C 档**时把 platform 下四子目录拆成独立 `*-service` 即可，接口契约不变。
5. 迁移期 `_transition/` 保留 d2–d9；**新代码只写 `libs/*` 与 `services/*`**。

---

## 11. 维护约定

- 目录树变更 → 更新本文 §2–§3
- 新增接口 → `gnex-contracts` + 本文 §4
- Phase 关账 → 同步 [ARCHITECTURE.md](./ARCHITECTURE.md) 演进表
