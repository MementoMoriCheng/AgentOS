# Agent OS 架构设计文档

> **版本**：v1.0  
> **日期**：2026-06-15  
> **状态**：团队评审基线  
> **目标**：为生产级、多租户、可伸缩到 1 万+ agent 的智能中枢平台定义开发与部署架构

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [术语对齐](#2-术语对齐)
3. [核心架构决策](#3-核心架构决策)
4. [整体架构总览](#4-整体架构总览)
5. [控制面：模块化单体设计](#5-控制面模块化单体设计)
6. [执行面：沙箱池设计](#6-执行面沙箱池设计)
7. [状态面：状态外化设计](#7-状态面状态外化设计)
8. [消息总线：调度平面设计](#8-消息总线调度平面设计)
9. [API 网关：外部入口设计](#9-api-网关外部入口设计)
10. [多 Agent 通信与协作模式](#10-多-agent-通信与协作模式)
11. [状态维持与故障恢复](#11-状态维持与故障恢复)
12. [资源管理与生命周期](#12-资源管理与生命周期)
13. [开发与部署的解耦](#13-开发与部署的解耦)
14. [演进路径](#14-演进路径)
15. [关键工程约束（必须遵守）](#15-关键工程约束必须遵守)
16. [与 OpenClaw 架构的对比](#16-与-openclaw-架构的对比)
17. [参考来源](#17-参考来源)

---

# 第二部分：Harness 综合集成与原语编译层设计

> **以下章节（18-26）记录了 GNEX 如何通过适配器层实现"任何 Agent 框架的 Harness 都能在 GNEX 上运行"的设计决策。**
> **核心目标：从"蒸馏单一框架"演进到"原语编译层"，使 GNEX 成为可加载各类 Harness 副本的真正企业级智能化中枢。**

18. [Harness 综合集成：目标与设计动机](#18-harness-综合集成目标与设计动机)
19. [Harness 的三层结构与可蒸馏性分析](#19-harness-的三层结构与可蒸馏性分析)
20. [三条集成路线的对比与决策](#20-三条集成路线的对比与决策)
21. [五大核心差异的深度分析](#21-五大核心差异的深度分析)
22. [适配器层架构：动态映射与复合操作](#22-适配器层架构动态映射与复合操作)
23. [核心原语集定义（7 个原语）](#23-核心原语集定义7-个原语)
24. [io 与 pub/sub 的独立性分析](#24-io-与-pubsub-的独立性分析)
25. [read/write 的 source/target 格式设计](#25-readwrite-的-sourcetarget-格式设计)
26. [框架映射表与编译规则](#26-框架映射表与编译规则)
27. [三层嵌套 ReAct 结构](#27-三层嵌套-react-结构)

---

## 1. 背景与目标

### 1.1 业务定位

为生产型企业提供部署和企业服务的 **Agent OS（智能中枢平台）**，支持多租户、合规审计、不可信代码执行。

### 1.2 规模预期

| 维度 | 当前 | 未来目标 |
|------|------|---------|
| 同时在线 agent | < 500 | 1 万+ |
| 租户 | 多企业租户 | 持续增长 |
| 代码可信度 | 不可信（需沙箱隔离） | 不变 |
| 合规要求 | 需审计、可回放 | 不变 |

### 1.3 设计原则

1. **为未来设计，但不过度设计当下**：当前不到 500 agent，但架构必须具备伸缩到 1 万的能力
2. **开发与部署解耦**：开发时模块化单体，部署时分布式多副本，代码零改动
3. **控制面与执行面分离**：编排逻辑是纯逻辑（不需要 OS 隔离），沙箱执行是计算单元（必须隔离）
4. **状态外化**：所有持久状态从一开始就不放进程内存

---

## 2. 术语对齐

> **本节极其重要——本次架构讨论中大量混淆源于术语的多义性。以下定义是团队共识，后文全部使用这套词汇。**

### 2.1 "Runtime" 的三种含义（必须区分）

| 层次 | 含义 | 本质 | 是否需要沙箱 |
|------|------|------|-------------|
| **Agent Loop（智能体循环）** | think→decide→call_tool→observe 的循环 | 纯 Python while 循环 + LLM API 调用 | ❌ 不需要 |
| **Orchestration（编排）** | 多 Agent 调度、任务拆解、路由、聚合 | 纯逻辑（图遍历 / 消息分发） | ❌ 不需要 |
| **Action Execution（动作执行）** | 真正执行 bash、写文件、跑模型生成的代码 | 有操作系统级副作用 | ✅ 必须 |

**结论**：Agent 的"大脑"（Agent Loop + Orchestration）不需要沙箱；Agent 的"手脚"（Action Execution）才需要沙箱。

### 2.2 "Gateway" 的两种理解（必须区分）

| 来源 | Gateway 的含义 |
|------|---------------|
| **通用 Web 领域（Nginx/Envoy）** | 外部 HTTP/API 入口，负责 SSL、限流、负载均衡 |
| **OpenClaw 的 Gateway** | 四合一超级中枢 = 入口 + 消息路由 + 编排器 + 状态管理 |

**本文档约定**：Gateway 专指**外部 API 入口**（Nginx/Envoy），不承担业务调度职责。控制面到执行面的调度走**消息总线（Message Bus）**。

### 2.3 "Sandbox" 的两层含义

| 层次 | 含义 | 典型实现 |
|------|------|---------|
| **上下文沙箱**（Context Sandbox） | 子 agent 有独立上下文窗口，推理状态隔离 | LangGraph State、Swarm context_variables |
| **执行沙箱**（Compute Sandbox） | OS 级隔离容器，跑代码/shell/文件 IO | Docker 容器、E2B、Daytona |

**本文档中"沙箱"默认指执行沙箱（Compute Sandbox）。**

### 2.4 原语的三种性质

| 原语类型 | 例子 | 有副作用吗 | 需要沙箱吗 |
|---------|------|-----------|-----------|
| **纯原语**（Pure） | `llm_call`、`memory_read`、`plan`、`route_to_agent` | 没有 | ❌ 不需要 |
| **内部副作用原语** | `update_state`、`append_message`、`checkpoint` | 有，但只在进程内 | ❌ 不需要 |
| **外部副作用原语**（Effectful） | `exec_bash`、`write_file`、`http_request` | 有，碰 OS/文件系统/网络 | ✅ 必须 |

**编排本身（决定调哪个原语、按什么顺序调）是纯逻辑，不需要沙箱。只有外部副作用原语在执行时才穿透到沙箱。**

### 2.5 "微服务"的两个切分维度

| 维度 | 含义 | 本文档的选择 |
|------|------|-------------|
| **部署单元**切分 | 不同的进程 / 容器 | 控制面多副本 + 沙箱独立容器 |
| **代码单元**切分 | 不同的代码仓库 / 服务 | 不拆，用模块化单体 + 接口解耦 |

---

## 3. 核心架构决策

### 决策 1：控制面做成"模块化单体"，不做微服务拆分

**理由**：编排器、IO、权限、审计、Agent Loop 之间的通信模式是**同步、高频、强事务**的——一个 agent 的每一步都要经过"编排决策→权限检查→执行→审计记录"，这是一个原子单元。拆成微服务会引入：
- 网络故障导致的分布式事务回滚
- 每步走 RPC 的序列化/反序列化开销
- 跨服务调试地狱
- 1 万并发时服务间 RPC 成为吞吐瓶颈

### 决策 2：沙箱执行层必须独立拆成执行面

**理由**：沙箱是**计算单元**，需要 OS 隔离、独立伸缩、可丢弃重建、执行不可信代码。性质和控制面完全不同，必须物理分离。这是 Kubernetes 把 controller（控制面单体）和容器（执行单元）分开的同一理由。

### 决策 3：状态全部外化，控制面无状态

**理由**：控制面要多副本水平扩展，必须无状态。所有持久状态外化到 State Plane（Redis + Postgres + Kafka）。

### 决策 4：开发单体 + 部署微服务，靠接口（Port）解耦

**理由**：开发阶段所有模块打包成一个单体一起开发，模块间通过接口（Protocol/ABC）通信，零网络开销。部署时按需起多副本、换远程实现，代码零改动。

---

## 4. 整体架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        Agent OS 整体架构                          │
│                                                                   │
│  外部用户                                                         │
│     │                                                             │
│     │  HTTPS / WebSocket                                         │
│     ▼                                                             │
│  ┌──────────────────────┐                                        │
│  │  ① API Gateway       │  外部入口（Nginx/Envoy）               │
│  │  (SSL/限流/WS/鉴权)  │  纯基础设施，不做业务调度              │
│  └──────────┬───────────┘                                        │
│             │  负载均衡到控制面多副本                              │
│        ┌────┼────┐                                               │
│        ▼    ▼    ▼                                               │
│  ┌─────┐┌─────┐┌─────┐                                          │
│  │控制面││控制面││控制面│  ② 模块化单体（同一个镜像，多副本）     │
│  │ #1  ││ #2  ││ #N  │                                         │
│  │     ││     ││     │  编排器 + IO + 权限 + 审计 + Agent Loop │
│  │     ││     ││     │  无状态，水平扩展                        │
│  └──┬──┘└──┬──┘└──┬──┘                                          │
│     │      │      │  控制面之间不直接通信                         │
│     └──────┼──────┘                                              │
│            │                                                     │
│     ┌──────┴──────┐                                              │
│     │             │  读写状态 / 发收事件                          │
│     ▼             ▼                                              │
│  ┌───────────────────────────────────────┐                       │
│  │  ③ State Plane（状态面）              │                       │
│  │  ├─ Redis：热状态 + 沙箱注册表 + 锁   │                       │
│  │  ├─ Postgres：checkpoint + 审计日志   │                       │
│  │  └─ Kafka：事件流（可回放）           │                       │
│  └───────────────────────────────────────┘                       │
│                                                                   │
│  ┌───────────────────────────────────────┐                       │
│  │  ④ Message Bus（消息总线/调度平面）    │                       │
│  │  控制面 ↔ 沙箱 之间的消息路由          │                       │
│  │  Topic: actions.{sandbox_id}          │                       │
│  │  Topic: observations.{sandbox_id}     │                       │
│  │  实现：Kafka / NATS / Redis Stream    │                       │
│  └──────────────────┬────────────────────┘                       │
│                     │                                             │
│        ┌────────────┼────────────┐                               │
│        ▼            ▼            ▼                               │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐                         │
│   │ 沙箱 #1  │  │ 沙箱 #2  │  │ 沙箱 #N │  ⑤ 执行面              │
│   │ 容器     │  │ 容器     │  │ 容器    │  消费 Action            │
│   │          │  │          │  │         │  产出 Observation       │
│   └─────────┘  └─────────┘  └─────────┘                         │
│                                                                   │
│  ┌───────────────────────────────────────────────────┐           │
│  │  Agent Framework SDK（共享代码库，一份代码）        │           │
│  │  被控制面导入，也被沙箱镜像导入                     │           │
│  │  定义 agent 行为逻辑、工具集、原语接口              │           │
│  └───────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

### 调用关系总表

| 调用关系 | 走法 | 说明 |
|---------|------|------|
| 用户 → 系统 | 用户 → API Gateway → 控制面 | Gateway 只管外部入口 |
| 控制面 → 沙箱 | 控制面 → Message Bus → 沙箱 | 不经过 API Gateway |
| 控制面 ↔ 状态 | 控制面 ↔ Redis/Postgres/Kafka | 状态外化 |
| 控制面 ↔ 控制面 | 不直接通信，通过 State Plane 间接协作 | 无状态多副本 |
| 沙箱 → 控制面 | 沙箱 → Message Bus → 控制面 | 结果回传 |

---

## 5. 控制面：模块化单体设计

### 5.1 模块划分

```
agent-os/
├── src/
│   ├── core/               # Agent Loop + 原语定义（核心域）
│   │   ├── agent_loop.py   # think-act 循环
│   │   ├── primitives.py   # 原语接口（llm_call, exec_bash, ...）
│   │   └── state.py        # Agent 状态管理接口
│   │
│   ├── orchestration/      # 多 Agent 编排（编排模块）
│   │   ├── supervisor.py   # 任务拆解、路由、聚合
│   │   ├── scheduler.py    # Agent ↔ 沙箱调度
│   │   └── patterns/       # 编排模式
│   │       ├── pipeline.py
│   │       ├── handoff.py
│   │       └── blackboard.py
│   │
│   ├── auth/               # 权限控制
│   │   ├── permission.py   # 权限检查接口 + 实现
│   │   └── tenant.py       # 多租户隔离逻辑
│   │
│   ├── audit/              # 审计日志（旁路写入）
│   │   ├── logger.py       # 审计记录接口
│   │   └── recorder.py     # 事件录制
│   │
│   ├── execution/          # 沙箱执行适配器（只含客户端/调用方）
│   │   ├── port.py         # SandboxPort 接口定义 ★ 关键边界
│   │   ├── local.py        # 本地实现（开发时用）
│   │   └── remote.py       # 远程实现（部署时用，走 Message Bus）
│   │
│   ├── io/                 # API 接口层
│   │   ├── api.py          # REST API 端点
│   │   └── websocket.py    # WebSocket 处理
│   │
│   └── infra/              # 基础设施适配
│       ├── redis_client.py
│       ├── postgres_client.py
│       └── kafka_client.py
│
├── shared/                 # 接口定义、协议、数据类型（契约层）
│   ├── ports.py            # 所有 Port 定义
│   ├── types.py            # Action, Observation, Session, ...
│   └── events.py           # 事件类型定义
│
├── sandbox-runtime/        # 沙箱执行端（独立组件，打进沙箱镜像）
│   ├── action_executor.py  # 接收 Action，执行，返回 Observation
│   ├── docker_executor.py  # Docker 沙箱实现
│   └── server.py           # 沙箱 HTTP/gRPC 服务端
│
└── config/
    ├── agents/             # Agent 定义（YAML 配置，不是代码分支）
    │   ├── researcher.yaml
    │   ├── coder.yaml
    │   └── reviewer.yaml
    └── deployment/         # 部署配置
        ├── docker-compose.dev.yml    # 开发环境
        ├── docker-compose.staging.yml # 预发布环境
        └── k8s/                       # 生产 K8s 配置
```

### 5.2 端口-适配器架构（Hexagonal Architecture）

**核心规则**：每个模块只暴露一个明确的接口（Port），内部实现对其他模块不可见。

```
依赖方向（严格单向，禁止循环）：

io (API 网关端点)
  → orchestration (编排)
      → auth (权限)
      → core (Agent Loop / 原语)
          → execution/port (执行接口定义) ★ 这是关键边界
      → infra (基础设施适配)

audit (审计) ← 旁路监听，不参与主链路
infra (状态存储) ← 底层，被所有人依赖
```

- `core` 模块**不 import 任何上层模块**——它只定义接口，由上层注入实现
- `orchestration` 依赖的是 `SandboxPort` 这个**接口**，不是 `DockerExecutor` 这个**实现**
- 负责编排的人和负责沙箱的人，只需要协商接口定义

### 5.3 接口定义示例（Port / Protocol）

```python
# shared/ports.py

from typing import Protocol
from shared.types import Action, Observation, SessionId, AgentId, SandboxId


class SandboxPort(Protocol):
    """沙箱执行端口 —— 控制面通过这个接口调用沙箱"""

    async def create(self, config: "SandboxConfig") -> SandboxId:
        """创建一个沙箱实例"""
        ...

    async def exec_action(self, sandbox_id: SandboxId, action: Action) -> Observation:
        """在指定沙箱中执行一个动作"""
        ...

    async def destroy(self, sandbox_id: SandboxId) -> None:
        """销毁沙箱实例"""
        ...


class StatePort(Protocol):
    """状态存储端口 —— 控制面通过这个接口读写状态"""

    async def get_session(self, session_id: SessionId) -> "Session":
        ...

    async def save_session(self, session: "Session") -> None:
        ...

    async def checkpoint(self, session_id: SessionId, state: dict) -> None:
        ...


class MessageBusPort(Protocol):
    """消息总线端口 —— 控制面通过这个接口收发事件"""

    async def publish(self, topic: str, message: dict) -> None:
        ...

    async def subscribe(self, topic: str, handler: callable) -> None:
        ...


class AuthPort(Protocol):
    """权限检查端口"""

    async def check_permission(
        self, tenant_id: str, agent_id: AgentId, action: Action
    ) -> bool:
        ...


class AuditPort(Protocol):
    """审计端口（旁路）"""

    async def record(self, event: "AuditEvent") -> None:
        ...
```

### 5.4 开发时的依赖注入（零网络开销）

```python
# 开发时：所有模块在同一个进程里，直接注入实现

# execution/local.py
class LocalSandboxExecutor:
    """本地沙箱执行器（开发时用，同进程直接执行）"""

    async def exec_action(self, sandbox_id, action):
        # 直接调用本地 Docker 执行
        result = await docker_run(action.cmd)
        return Observation(output=result)


# main.py（开发环境启动）
orchestrator = Orchestrator(
    executor=LocalSandboxExecutor(),     # ← 本地实现
    state=RedisStatePort(host="localhost"),
    bus=RedisStreamBus(host="localhost"),
    auth=LocalAuthPort(),
    audit=LocalAuditPort(),
)
```

### 5.5 部署时的依赖注入（走 Message Bus）

```python
# execution/remote.py
class RemoteSandboxExecutor:
    """远程沙箱执行器（部署时用，走消息总线）"""

    async def exec_action(self, sandbox_id, action):
        # 发到 Message Bus，等沙箱消费后回传
        response = await self.bus.request(
            topic=f"actions.{sandbox_id}",
            payload=action.to_dict(),
            timeout=300,
        )
        return Observation.from_dict(response)


# main.py（生产环境启动）
orchestrator = Orchestrator(
    executor=RemoteSandboxExecutor(),    # ← 远程实现
    state=RedisStatePort(host=REDIS_CLUSTER),
    bus=KafkaBus(brolers=KAFKA_BROKERS),
    auth=RemoteAuthPort(),
    audit=KafkaAuditPort(),
)
```

**关键：Orchestrator 的代码一行都不用改，只换注入的实现。**

### 5.6 Agent 定义示例（配置化，不是代码分支）

```yaml
# config/agents/researcher.yaml
name: researcher
model: claude-sonnet-4
tools: [bash, file_read, web_search]
prompt: |
  你是一个研究型 agent，负责收集和整理信息。
max_steps: 50
sandbox:
  cpu: 2
  memory: 4Gi
  timeout: 1800s
  network_whitelist: ["*.wikipedia.org", "*.arxiv.org"]
checkpoint:
  frequency: every_step
```

**不同 agent = 不同 YAML 文件，不是不同代码分支。新增一个 agent 类型 = 加一个 YAML，不改框架代码。**

### 5.7 团队分工建议

```
团队分工：
├─ 小 A 负责 core/           → Agent Loop 和原语定义
├─ 小 B 负责 orchestration/  → 编排逻辑，通过接口调 core 和 execution
├─ 小 C 负责 execution/      → 沙箱执行适配器，实现 SandboxPort 接口
├─ 小 C 负责 sandbox-runtime/→ 沙箱执行端（独立组件）
├─ 小 D 负责 auth/ + audit/  → 权限和审计
└─ 小 E 负责 io/ + infra/    → API 网关端点和基础设施适配

每个模块的对外契约 = 一个 interface 文件（shared/ports.py）
只要契约不变，内部实现随便改，不影响其他人
这和微服务的开发体验几乎完全一样——契约驱动、接口隔离、独立开发
区别只是它在同一个进程里（省了 RPC），而不是跨进程
```

---

## 6. 执行面：沙箱池设计

### 6.1 沙箱的职责（单一）

沙箱**只负责执行动作，不持有任何持久状态**：

```
沙箱的生命周期：
  创建 → 接收 Action → 执行 → 返回 Observation → （空闲超时后）销毁
```

### 6.2 沙箱的属性

| 属性 | 值 |
|------|-----|
| 隔离级别 | OS 级（Docker 容器 / VM） |
| 状态 | 无状态（可丢弃、可重建） |
| 伸缩 | 独立于控制面，按需起容器 |
| 生命周期 | 短暂（任务完成或超时后回收） |
| 通信 | 只通过 Message Bus，不直接被控制面 RPC |

### 6.3 沙箱池管理

```
┌──────────────────────────────────────────┐
│  Sandbox Registry（沙箱注册表）           │
│  存储在 Redis 中                         │
│                                          │
│  sandbox-001: busy (agent A, session X)  │
│  sandbox-002: idle                       │
│  sandbox-003: busy (agent B, session Y)  │
│  sandbox-004: creating                   │
│  sandbox-005: dead (timeout)             │
│  ...                                     │
└──────────────────────────────────────────┘
```

- 控制面从 Registry 查空闲沙箱 → 分配任务
- 沙箱执行完 → 更新状态为 idle
- 健康检查（心跳）→ 30 秒无心跳标记为 dead → 触发恢复

### 6.4 沙箱技术选型

| 方案 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| 自建 Docker 容器 | 开发/测试 | 完全可控 | 运维成本高 |
| K8s Pod | 生产 | 自动调度、弹性伸缩 | 需要 K8s 集群 |
| E2B / Daytona | 托管生产 | 免运维、按需付费 | 供应商锁定 |
| Modal | Serverless | 极简、自动伸缩 | 冷启动延迟 |

---

## 7. 状态面：状态外化设计

### 7.1 状态分类与存储

| 状态类型 | 存哪 | 技术选型 | 特点 |
|---------|------|---------|------|
| 对话上下文（messages） | Checkpoint Store | Postgres | 持久、可查询 |
| 会话级热状态（任务进度、变量） | KV Store | Redis | 低延迟 |
| 沙箱注册表 | KV Store | Redis | 高频读写 |
| 分布式锁 | KV Store | Redis（SETNX） | 并发控制 |
| 文件产物 | Object Store | S3 / MinIO | 大文件、共享卷 |
| 结构化业务状态 | 业务数据库 | Postgres | 事务一致性 |
| 事件流（审计/回放） | Event Store | Kafka | 不可变、可回放 |

### 7.2 Event Sourcing 模式

所有状态变更都表示为**事件**：

```
事件类型：
  AgentStarted         → agent 开始执行
  ActionDispatched     → 控制面分发了一个 Action 到沙箱
  ActionExecuted       → 沙箱执行完一个 Action
  ObservationReturned  → 沙箱回传了 Observation
  CheckpointSaved      → 控制面保存了 checkpoint
  AgentFinished        → agent 执行完成
  ErrorOccurred       → 发生错误
```

- 事件写入不可变日志（Kafka），任何组件都能回放重建状态
- 当前状态 = 初始状态 + 事件回放（和 Git 的原理一样）
- 即使控制面全挂了，重启后从 Kafka 回放就能恢复全部状态

### 7.3 CQRS（读写分离）

- **写路径**：控制面把每次状态变更作为事件写入 Kafka，再异步投影到 Postgres/Redis
- **读路径**：控制面从 Redis 读热状态（低延迟），从 Postgres 读历史（可查询）

---

## 8. 消息总线：调度平面设计

### 8.1 消息总线的职责

控制面和沙箱之间的**唯一通信通道**：

- 控制面把 Action 写到 topic `actions.{sandbox_id}`
- 沙箱订阅自己的 topic，消费 Action，执行完把 Observation 写回 topic `observations.{sandbox_id}`
- 控制面订阅结果 topic，拿到 Observation 继续

### 8.2 Topic 设计

```
actions.{sandbox_id}        ← 控制面写入，沙箱消费
observations.{sandbox_id}   ← 沙箱写入，控制面消费
agent_events.{session_id}   ← 全局事件流（审计用）
sandbox_lifecycle            ← 沙箱生命周期事件（创建/销毁/超时）
```

### 8.3 端到端调度流程

以一个 agent 执行 `ls -la` 为例：

```
1. 控制面编排决策："下一步执行 bash: ls -la，分配给沙箱#2"

2. 控制面写事件到 Message Bus：
   topic = "actions.002"
   payload = { action: "exec_bash", cmd: "ls -la", request_id: "abc123" }

3. 沙箱#2 订阅了 "actions.002"，消费到这条消息

4. 沙箱#2 执行 ls -la，产出结果

5. 沙箱#2 写事件到 Message Bus：
   topic = "observations.002"
   payload = { request_id: "abc123", output: "file1.txt\nfile2.txt" }

6. 控制面订阅了 "observations.002"，消费到这条消息，拿到结果

7. 控制面更新 State Plane：
   - Redis：更新 agent 状态（把 observation 加到 messages）
   - Postgres：写 checkpoint
   - Kafka：这条事件本身就是审计记录
```

**关键**：控制面和沙箱互相不直接知道对方的 IP 地址，只认 topic。

### 8.4 技术选型对比

| 维度 | Kafka | NATS | Redis Stream |
|------|-------|------|-------------|
| 吞吐量 | 10 万+ msg/s | 100 万+ msg/s | 10 万 msg/s |
| 持久化 | 强（磁盘） | 可选 | 中（内存/磁盘） |
| 事件回放 | ✅ 原生支持 | ⚠️ 需配置 | ✅ 支持 |
| 运维复杂度 | 高（集群） | 低（单二进制） | 低（Redis 自带） |
| 延迟 | 毫秒级 | 微秒级 | 毫秒级 |
| 生态 | 最成熟 | 新兴 | Redis 生态 |
| **推荐场景** | **生产级大规模** | **高性能中规模** | **开发/小规模** |

**建议**：开发阶段用 Redis Stream，生产切换到 Kafka。

---

## 9. API 网关：外部入口设计

### 9.1 职责（纯基础设施）

API Gateway **只负责外部入口**，不参与内部调度：

- SSL 终止
- 用户身份验证（JWT/OAuth）
- 请求限流
- WebSocket 连接管理（粘性路由）
- 负载均衡到控制面多副本

### 9.2 为什么 API Gateway 不参与内部调度

1. **内部调用量远大于外部**：1 万 agent 时，控制面↔沙箱每秒上万次调用，过 Gateway 会成为瓶颈
2. **Gateway 不是服务发现工具**：沙箱的发现靠 Redis 里的注册表，不靠 Gateway
3. **职责分离**：Gateway 管外部信任边界，内部组件已被信任

### 9.3 技术选型

用现成的：Nginx / Envoy / Kong，不用自己写。

---

## 10. 多 Agent 通信与协作模式

### 10.1 四种主流模式

| 模式 | 通信方式 | 状态管理 | 适用场景 |
|------|---------|---------|---------|
| **Pipeline（顺序流水线）** | Handoff 接力 | 各自独立 + 聚合 | A→B→C 固定顺序 |
| **Router（并行无交互）** | Fan-out + Fan-in | 各自独立 | A,B,C 同时跑完汇总 |
| **Blackboard（黑板模型）** | 共享状态读写 | 共享黑板 | 并行需交互、复杂推理 |
| **Hub-and-spoke（编排器中转）** | 编排器中转 | 编排器持有全局 | 强集中控制 |

### 10.2 顺序执行场景（Pipeline）

```
[沙箱 A] 执行完 → 把结果写到 State Plane
                          ↓
[沙箱 B] 启动时从 State Plane 读 A 的结果 → 执行 → 写自己的结果
                          ↓
[沙箱 C] 启动时读 B 的结果 → 执行 → 完成
```

- 轻量数据（JSON/文本）走 Message Bus
- 大文件产物写 S3，传 URL
- 上下文传递靠 context handoff（上一个 agent 的 messages 摘要）

### 10.3 并行协场景（黑板 / 消息总线）

**黑板模型**：
- 所有 agent 读写同一个共享状态（Redis）
- 每个 agent 只订阅自己关心的字段
- 字段变化触发事件，订阅该字段的 agent 被唤醒
- 并发写冲突靠乐观锁/CAS 解决

**消息总线模式**：
- 每个 agent 把结果作为事件发布到 Kafka
- 其他 agent 或编排器订阅消费
- 异步、解耦、天然支持并行

---

## 11. 状态维持与故障恢复

### 11.1 Snapshotting + Rehydration

```
正常流程：
  沙箱执行 step N → 控制面收到 Observation
  → 写 checkpoint(step N) 到 Postgres → 派发 step N+1

容器挂了：
  检测到沙箱不可用 → 读最近 checkpoint(step N)
  → 启一个新沙箱 → 把 step N 的 state 重新注入 → 从 step N+1 继续
```

### 11.2 检查点策略

| 策略 | 频率 | 安全性 | 性能开销 |
|------|------|--------|---------|
| 每步检查点（every_step） | 每个 action 后 | 最高 | 较高 |
| 周期检查点（every_K_steps） | 每 K 步 | 中 | 低 |
| 关键点检查点（on_milestone） | 关键节点 | 中 | 最低 |

**建议**：默认每步检查点（简单可靠），性能优化时切换为周期检查点。

### 11.3 恢复流程

1. 检测到沙箱不可用（心跳超时）
2. 从 Postgres 读最近 checkpoint
3. 启一个新沙箱（用同样的 manifest 复刻环境）
4. 把 checkpoint 中的 state 重新注入
5. 从上一步的下一步继续执行
6. 已执行的步骤不重跑（靠幂等性保证）

### 11.4 幂等性要求

重试时同一个 action 执行两次不能产生不同结果：
- 写文件用"覆盖"而非"追加"
- API 调用带 idempotency_key
- 数据库操作用 UPSERT

---

## 12. 资源管理与生命周期

### 12.1 沙箱生命周期

```
创建 ─→ 健康检查 ─→ 执行任务 ─→ 空闲 ─→ 超时回收 ─→ 销毁
```

### 12.2 资源配额

| 资源 | 限制方式 | 示例 |
|------|---------|------|
| CPU/内存 | cgroup / K8s resource limit | 2 核 4Gi |
| 网络出站 | 白名单 | 只允许访问 *.wikipedia.org |
| 空闲超时 | 定时器 | 10 分钟无动作回收 |
| 最大执行时长 | 定时器 | 1 小时强杀 |
| 磁盘 | 容器 tmpfs / 挂载卷 | 10Gi |

### 12.3 沙箱预热池

维持一定数量的 warm sandbox 待命，避免冷启动延迟：
- 池大小根据负载动态调整
- 例如：当前活跃 agent 数 × 20%

---

## 13. 开发与部署的解耦

### 13.1 核心原则

**代码是一份，部署是多个。** 开发时模块化单体（一个进程），部署时控制面多副本 + 沙箱独立容器。

### 13.2 开发环境

```
开发环境（本地 Docker Compose）：
├─ 控制面单体（1 个进程）
│   所有模块打包，通过接口注入本地实现
├─ 状态层：本地 Redis + 本地 Postgres
├─ 消息层：本地 Redis Stream
├─ 沙箱：本地 Docker 容器
└─ 目标：10-50 个 agent 跑通完整流程
```

### 13.3 部署环境（三阶段演进）

```
阶段 1（MVP，单体跑通）：
  ├─ 控制面单体（所有模块打包）
  ├─ 状态层：本地 Redis + SQLite/Postgres
  ├─ 消息层：本地 Redis Stream
  ├─ 沙箱：本地 Docker 容器
  └─ 目标：10-50 个 agent 跑通完整流程

阶段 2（验证伸缩性）：
  ├─ 控制面：2-3 个副本 + Nginx 负载均衡
  ├─ 状态层：Redis（单节点）+ Postgres（单节点）
  ├─ 消息层：Redis Stream 或单节点 Kafka
  ├─ 沙箱：Docker 池（50-100 个容器）
  └─ 目标：100-500 个 agent 并发

阶段 3（生产级）：
  ├─ 控制面：10+ 副本，K8s 部署
  ├─ 状态层：Redis Cluster + Postgres 主从
  ├─ 消息层：Kafka 集群（3-5 broker）
  ├─ 沙箱：K8s Pod 池 或 E2B/Daytona
  └─ 目标：1000-10000 agent
```

**关键：从阶段 1 到阶段 3，代码不动，只换配置和基础设施。**

### 13.4 Agent Framework SDK

```
agent-framework-sdk/          ← 一个 Git 仓库，一个代码库
├── core/                     ← agent loop + 原语
├── orchestration/            ← 编排模式
├── tools/                    ← 工具实现
├── patterns/                 ← supervisor/handoff/blackboard
├── interface/                ← 和控制面/状态面通信的接口
└── pyproject.toml            ← 版本化管理
```

- 发版本号（v1.0、v1.1...）
- 控制面镜像 `pip install agent-framework-sdk==1.2.3`
- 沙箱镜像也 `pip install agent-framework-sdk==1.2.3`
- **代码协作问题用正常的 Git 工作流解决**——code review、feature branch、CI/CD

---

## 14. 演进路径

### 14.1 推荐的开发顺序

```
Step 1：定义接口（shared/ports.py）
  ├─ SandboxPort
  ├─ StatePort
  ├─ MessageBusPort
  ├─ AuthPort
  └─ AuditPort

Step 2：实现 core/ 模块
  ├─ Agent Loop（think-act 循环）
  └─ 原语定义

Step 3：实现 orchestration/ 模块
  ├─ Supervisor（任务拆解、路由）
  └─ Scheduler（沙箱调度）

Step 4：实现 execution/ + sandbox-runtime/
  ├─ LocalSandboxExecutor（开发时）
  ├─ DockerExecutor
  └─ 沙箱执行端

Step 5：实现 auth/ + audit/ + io/ + infra/
  └─ 权限、审计、API 端点、基础设施适配

Step 6：集成测试（本地 Docker Compose）
  └─ 10-50 个 agent 跑通完整流程

Step 7：阶段 2 部署验证
  └─ 多副本 + 消息总线

Step 8：阶段 3 生产部署
  └─ K8s + Kafka + 沙箱池
```

---

## 15. 关键工程约束（必须遵守）

> **以下约束从项目第一天就要遵守，否则后期从单体切分布式时代码改动巨大。**

### 约束 1：模块边界从第一天用接口定义

```python
# ✅ 正确：依赖接口
class Orchestrator:
    def __init__(self, executor: SandboxPort):  # 接口
        self.executor = executor

# ❌ 错误：依赖具体实现
class Orchestrator:
    def __init__(self):
        self.executor = DockerExecutor()  # 写死了实现
```

### 约束 2：依赖方向严格单向，禁止循环依赖

```
io → orchestration → auth → core → execution_port
                                        ↓
                                     infra
```

- 每一层只能向下依赖，不能向上
- `core` 不 import 任何上层模块

### 约束 3：状态从第一天外化

```python
# ✅ 正确：状态存在 Redis
session = await redis.get(f"session:{session_id}")

# ❌ 错误：状态存在进程内存
self.sessions[session_id] = session  # 多副本时无法共享
```

### 约束 4：审计/事件流从第一天就走消息总线

```python
# ✅ 正确：每个 action 都作为事件发出
await bus.publish("agent_events.session_xxx", {
    "type": "ActionExecuted",
    "agent_id": "agent_a",
    "action": "exec_bash",
    "timestamp": "...",
    "result": "...",
})

# ❌ 错误：只写本地日志文件
logger.info(f"Agent A executed bash")  # 多副本时日志散落各处
```

### 约束 5：沙箱接口从第一天就按"远程"设计

```python
# 从第一天就定义好这个接口
class SandboxPort(Protocol):
    async def create(self, config: SandboxConfig) -> SandboxId: ...
    async def exec_action(self, sandbox_id: SandboxId, action: Action) -> Observation: ...
    async def destroy(self, sandbox_id: SandboxId) -> None: ...

# 开发时注入 LocalSandboxExecutor（同进程）
# 部署时注入 RemoteSandboxExecutor（走 Message Bus）
# 接口不变，切换实现即可
```

### 约束 6：控制面必须无状态

控制面实例不持有任何跨请求的状态。所有持久状态外化到 State Plane。这样多副本才能正常工作。

### 约束 7：编排器不直接执行命令

编排器只决定"要执行什么命令"，然后把命令委托给沙箱执行。编排器本身不碰 bash/文件系统。

---

## 16. 与 OpenClaw 架构的对比

### 16.1 OpenClaw 的 Gateway 设计

OpenClaw 的 Gateway 是**四合一超级中枢**：

```
OpenClaw Gateway（一个进程里包含的功能）：
├─ ① 外部入口层（WebSocket、HTTP、IM 渠道接入）
├─ ② 消息路由层（Session Key 路由、上下文隔离）
├─ ③ 编排层（Agent Runner、Agent Loop、队列调度）
└─ ④ 状态管理层（Session、RuntimeState）
```

官方定位为 **hub-and-spoke（中心辐射型）** 设计，推荐部署模型是"每台主机一个 Gateway"。

### 16.2 核心对比

| 维度 | OpenClaw（单 Gateway 枢纽） | 本方案（分布式四层） |
|------|----------------------------|---------------------|
| 拓扑 | 中心辐射型 | 去中心化分布式 |
| 消息路由 | 所有消息经过中心 Gateway | 通过 topic 路由 |
| 状态 | Gateway 进程内持有 | 外化到 Redis/Postgres |
| 扩展性 | 单实例瓶颈 | 天然水平扩展 |
| 一致性 | 强一致（单点=真相） | 最终一致（事件回放） |
| 故障恢复 | Gateway 挂=全挂 | 单副本挂=影响小 |
| 复杂度 | 低 | 高 |
| 适用规模 | 几十~几百 agent | 几千~上万 agent |

### 16.3 值得借鉴的 OpenClaw 设计

虽然部署架构不同，但 OpenClaw 的以下设计非常值得学习：

| 设计 | 价值 |
|------|------|
| **ChannelPlugin 统一契约** | 50+ IM 渠道用一套接口抽象，新增渠道=写插件 |
| **Session Key 路由** | `agent:{agentId}:{channel}:{peerId}` 优雅的会话键设计 |
| **Agent Loop 六阶段** | intake→context→inference→tool→stream→persist |
| **三种 Agent 运行模式** | Embedded PI / CLI Agent / ACP（远程），按需选择 |
| **dmScope 隔离策略** | main / per-peer / per-channel-peer / per-account-channel-peer |

---

## 17. 参考来源

### 架构与框架

- [OpenAI Agents SDK：原生沙箱与可迁移 Harness 设计](http://m.toutiao.com/group/7638052669185180200/) —— Separating harness and compute、snapshotting/rehydration、one sandbox or many
- [拆解 OpenHands (10)：Runtime](https://www.cnblogs.com/rossiXYZ/p/19656834) —— 客户端-服务器架构、EventStream、Observation 回传、每会话一个容器
- [OpenAI Swarm 解读（51CTO）](https://www.51cto.com/aigc/2467.html) —— 轻量级 handoff、几乎完全运行在客户端
- [从 Sub-Agents 到 Multi-Agent 的工程指南（网易）](https://www.163.com/dy/article/KJT71AG40556721V.html) —— 四种模式（Sub-Agents / Skills / Handoffs / Router）
- [一文讲清：7 种常见多 Agent 协作架构模式](http://m.toutiao.com/group/7644876255413666340/) —— Pipeline → Orchestrator-Worker → Hierarchical → Blackboard → P2P/Swarm
- [Harness Engineering：深度约束下的 Agent 能力最大化](http://m.toutiao.com/group/7623965925364023860/) —— 沙箱类型分级、工具约束、行为规则
- [LangGraph 多智能体设计模式（掘金）](https://juejin.cn/post/7591703562133684258) —— supervisor / hierarchical / networked 架构

### OpenClaw 架构

- [万字拆解 OpenClaw 的架构与设计（CSDN）](https://blog.csdn.net/qiwoo_weekly/article/details/158902150) —— Gateway 三层架构、ChannelPlugin 统一契约、Session Key 路由
- [OpenClaw 结构 Overview](http://m.toutiao.com/group/7624456533811823110/) —— hub-and-spoke、Agent Runner 六大功能、Agent Loop 六阶段
- [OpenClaw 多 Agent 模式](http://m.toutiao.com/group/7619266092736725514/) —— 一个网关进程里跑多个隔离智能体

### 工业先例

- **Kubernetes**：controller-manager 是模块化单体（含多个控制器），kubelet 和容器是独立执行单元 → 控制面/执行面分离
- **PostgreSQL**：后端进程是单体（解析器、优化器、执行器），查询可并行到多个 worker → 单体 + 并行执行
- **Ray**：driver 是单体控制逻辑，worker 是独立执行进程 → 共享框架 + 分布式执行
- **gRPC**：一份 proto 定义，多语言多端实现 → 接口驱动开发

---

## 附录 A：术语表

| 术语 | 定义 |
|------|------|
| **Agent OS** | 本项目，生产级智能中枢平台 |
| **控制面（Control Plane）** | 编排器 + IO + 权限 + 审计 + Agent Loop 的集合，模块化单体 |
| **执行面（Execution Plane）** | 沙箱池，每个沙箱一个容器 |
| **状态面（State Plane）** | Redis + Postgres + Kafka 的集合，所有持久状态的唯一真相源 |
| **消息总线（Message Bus）** | 控制面和沙箱之间的消息路由通道（Kafka/NATS/Redis Stream） |
| **API Gateway** | 外部用户入口（Nginx/Envoy），纯基础设施 |
| **Port（端口）** | 模块对外暴露的接口定义（Protocol/ABC） |
| **Adapter（适配器）** | Port 的具体实现（Local/Remote） |
| **Action** | 控制面发给沙箱的执行指令 |
| **Observation** | 沙箱执行后返回的结果 |
| **Checkpoint** | Agent 状态的持久化快照 |
| **Rehydration** | 从 checkpoint 恢复 Agent 状态 |
| **Sandbox Registry** | 沙箱注册表，记录所有沙箱的状态 |
| **Event Sourcing** | 所有状态变更表示为不可变事件 |

---

## 附录 B：决策记录

| 编号 | 决策 | 理由 | 日期 |
|------|------|------|------|
| D001 | 控制面做成模块化单体，不做微服务拆分 | 编排逻辑是强事务、高频内调的，拆成微服务引入不必要的分布式复杂度 | 2026-06-15 |
| D002 | 沙箱执行层独立拆成执行面 | 计算单元需要 OS 隔离、独立伸缩、可丢弃重建 | 2026-06-15 |
| D003 | 状态全部外化到 State Plane | 控制面要多副本水平扩展，必须无状态 | 2026-06-15 |
| D004 | 开发单体 + 部署微服务，靠 Port 解耦 | 开发效率 + 部署灵活性的最佳平衡 | 2026-06-15 |
| D005 | API Gateway 不参与内部调度 | 内部调用量远大于外部，Gateway 会成为瓶颈 | 2026-06-15 |
| D006 | 消息总线作为控制面↔沙箱的唯一通道 | 异步解耦、可回放、支持大规模并行 | 2026-06-15 |
| D007 | Agent 定义用 YAML 配置，不是代码分支 | 新增 agent 类型不改框架代码 | 2026-06-15 |
| D008 | 开发阶段消息总线用 Redis Stream，生产切换 Kafka | 开发简单性 + 生产可伸缩性 | 2026-06-15 |

---

> **本文档是团队开发的基线。如有架构变更，请更新决策记录（附录 B）并通知所有相关人员。**

---

# 第二部分：Harness 综合集成与原语编译层设计

---

## 18. Harness 综合集成：目标与设计动机

### 18.1 核心目标

GNEX 的终极目标不是"做一个 Agent 框架"，而是**做一个能承载各类 Agent 框架 Harness 的企业级智能化中枢平台**。

具体而言：
- 未来有新的 Harness（Claude Code、OpenClaw、Hermes、或未来新框架）都可以**作为 GNEX 控制面的一个实例副本运行**
- GNEX 提供统一的沙箱管理、状态外化、消息总线、审计合规等平台能力
- 不同框架的编排风格通过**适配器层**转译成 GNEX 框架能理解的逻辑
- GNEX 可以按需加载不同类型的实例化副本镜像，实现真正的弹性部署和灵活调度

### 18.2 设计动机

**为什么需要综合集成各类 Harness？**

1. **企业场景多样性**：不同企业、不同业务场景需要不同的编排风格。代码重构场景需要 Claude 风格的强控制 SubAgent；多渠道客服场景需要 OpenClaw 风格的灵活路由；持续学习场景需要 Hermes 风格的自进化。
2. **避免供应商锁定**：如果只支持一种框架，企业被绑死在该框架的演进节奏上。GNEX 作为中性平台，让企业自由选择编排风格。
3. **平台化竞争力**：GNEX 的核心竞争力不是"比 Claude 更会编排"，而是"能同时支持多种编排风格并统一管理"。

### 18.3 核心论点（团队共识）

不同框架的 Agent，本质上都是基于相同的核心机制运行的。差异不在于"能不能做什么"，而在于"怎么做"：

```
所有 Agent 框架的共同核心（五件事）：
  1. Agent 的创建和启动方式
  2. Agent 之间的调用和委派机制
  3. 子 Agent 的生命周期管理
  4. 会话/上下文的隔离和传递
  5. 执行结果的回传和报送方式

不同框架的差异 = 这五件事的实现方式不同
GNEX 要做的 = 把这五件事虚拟化成统一的底层原语
任何框架的 Harness = 被编译成这些原语的调用序列
```

**团队验证结论**：除上述五件事之外，工具执行模型的差异已被 `SandboxPort` 统一；安全/权限模型的差异可通过"平台层安全 ⊃ Harness 层安全"的合并规则解决；记忆系统的差异是最复杂的，但通过扩展原语集（memory 类操作 + Hook 机制）可以覆盖。

---

## 19. Harness 的三层结构与可蒸馏性分析

并非 Harness 的所有部分都可以被提取和复用。通过分析 Claude Code、OpenClaw、Hermes 三个框架，发现 Harness 实际上由三层构成，可蒸馏性完全不同：

### 19.1 三层结构

```
┌─────────────────────────────────────────────────┐
│  第 1 层：Platform Binding（平台绑定层）          │
│  ─ OpenClaw 的 50+ IM 渠道适配                   │
│  ─ Hermes 的 200+ 模型兼容补丁                    │
│  ─ Claude 的特定 API 调用方式                     │
│  → ❌ 不可蒸馏（和具体平台强绑定）                 │
│  → 这一层是各家独有的，不需要也不应该统一          │
├─────────────────────────────────────────────────┤
│  第 2 层：Harness Core（编排内核层）★ 可蒸馏     │
│  ─ 编排循环模式（ReAct / 六阶段 / 自进化双轮）     │
│  ─ 上下文管理策略（固定阈值 / 比例压缩）           │
│  ─ Agent 协作模式（SubAgent / Hub-spoke / P2P）   │
│  ─ 安全护栏（错误分类 / 自愈策略 / 工具约束）      │
│  ─ 生命周期 Hook（on_tool_call / on_session_end）  │
│  → ✅ 可蒸馏（这是 GNEX 真正要提取的东西）        │
├─────────────────────────────────────────────────┤
│  第 3 层：Model Interaction（模型交互层）         │
│  ─ 具体的 LLM API 调用                           │
│  ─ Token 计费                                    │
│  ─ 流式输出处理                                   │
│  → ⚠️ 部分可蒸馏（靠 LiteLLM 这类统一层解决）     │
└─────────────────────────────────────────────────┘
```

### 19.2 GNEX 的蒸馏目标

**锁定第 2 层（Harness Core）**。这是各家框架的"编排哲学"精华，可以被抽象、提取、复用。第 1 层不需要统一（各家独有），第 3 层靠第三方统一层（LiteLLM）解决。

### 19.3 三个框架的 Harness Core 差异对比

| 维度 | Claude Code | OpenClaw | Hermes |
|------|------------|----------|--------|
| **编排循环** | ReAct（think→act→observe） | 六阶段（intake→context→inference→tool→stream→persist） | 自进化双轮（Skill 生成 + RL 训练） |
| **Agent 协作** | SubAgent 模式（非 Fork/Fork），禁止嵌套 | hub-and-spoke，单 Gateway 多 agent | 动态 Skill 沉淀，子 Agent 隔离 |
| **上下文压缩** | 不主动压缩，靠 SubAgent 独立窗口隔离 | 固定 Token 阈值（如 18K/20K） | 比例压缩（窗口占用率 50%），头尾保护+中间摘要 |
| **安全护栏** | 工具约束 + 路径白名单 + 命令黑名单 | ChannelPlugin 安全策略 + dmScope 隔离 | 四层防御（14 种错误分类 + 自愈 + 子 Agent 隔离 + Skill 扫描） |
| **生命周期 Hook** | 前台/后台 Agent + 完成通知 | Agent Runner 六大功能 | 全生命周期（on_tool_call / on_memory_write / on_session_end） |
| **记忆/进化** | 无自进化，AGENTS.md 静态注入 | 无自进化，运行时状态 | **动态 Skill 沉淀 + RL 训练闭环** |

**关键洞察**：三个框架的差异不是"实现不同"，而是"编排哲学不同"：
- Claude：**控制优先**——SubAgent 严格隔离、禁止嵌套
- OpenClaw：**接入优先**——多渠道路由、Session Key 灵活隔离
- Hermes：**进化优先**——每次任务沉淀经验、自动生成 Skill

---

## 20. 三条集成路线的对比与决策

在讨论如何集成各类 Harness 时，评估了三条路线：

### 20.1 路线 A：整体黑盒运行（最简单）

```
GNEX 控制面 → 启动沙箱 → 沙箱里跑完整的第三方框架（原封不动）
```

- **可行性**：✅ 立刻能跑，Docker 里装个 Node.js + Claude Code 即行
- **GNEX 能做什么**：启动/停止/超时/资源配额/粗粒度审计
- **GNEX 做不了什么**：看不到内部决策过程、无法介入 SubAgent 管理、无法跨框架协作、无法细粒度审计
- **结论**：❌ 不满足企业级可观测性和可控性要求

### 20.2 路线 B：MCP 桥接（不改第三方代码，获得执行层可控）

```
第三方框架（原封不动）→ MCP Client → GNEX MCP Server → GNEX 沙箱
```

- **可行性**：✅ 能跑，GNEX 只需实现一个 MCP Server
- **比 A 多了什么**：执行走 GNEX 沙箱、细粒度审计（工具级）、平台级安全策略
- **仍然做不了什么**：编排过程仍是黑盒、SubAgent 管理不可控、跨框架协作不可能
- **结论**：⚠️ 可作为短期过渡方案，但不满足编排层可控性要求

### 20.3 路线 C：原语蒸馏与编译（最灵活，最终选择）

```
提取第三方框架的编排逻辑 → 编译成 GNEX 原语序列 → GNEX 全程可控
```

- **可行性**：✅ 可行，需要定义核心原语集 + 维护映射表
- **获得了什么**：执行可控 + 编排可控 + 审计最细粒度（决策级）+ 多租户全层隔离 + 跨框架 Agent 协作
- **代价**：开发工作量较大，需要逆向分析各框架并建立映射关系
- **结论**：✅ **最终选择此路线**

### 20.4 决策记录

> **D009：选择路线 C（原语蒸馏与编译），放弃黑盒和半黑盒方案。理由：企业应用必须保证可观测性和可控性，不可能接受黑盒或半黑盒状态。**

### 20.5 务实演进路径

虽然最终目标是路线 C，但实施时建议分阶段：

```
阶段 1：路线 C 整体适配
  └─ 先做一个框架的完整适配器（优先 Claude Code）
  └─ 把对方的编排行为整体翻译成 GNEX 原语序列
  └─ 验证"原语编译"的可行性

阶段 2：逐步精细化
  └─ 在适配过程中发现哪些部分可以抽象成独立的可混搭维度
  └─ 不需要一开始就拆分，让实践驱动拆分

阶段 3：平台化
  └─ 多个框架的 Harness 副本同时运行
  └─ 调度器按场景路由到不同风格的副本
```

---

## 21. 五大核心差异的深度分析

在确认走路线 C 后，对五个核心差异逐一分析了"是否构成蒸馏障碍"：

### 21.1 差异 1：工具执行模型

| 框架 | 工具定义方式 | 执行方式 |
|------|------------|---------|
| Claude Code | JSON Schema 函数调用 | MCP Server / 内置工具 |
| Hermes | 40+ 内置工具 + 自定义 RPC 脚本 | 内置执行 + Skill 扫描 |
| OpenClaw | read/write/edit/bash 四个原子工具 + ChannelPlugin | pi-agent-core 执行 |

**结论**：❌ **不构成障碍**。所有工具调用拆到底层都是"定义 schema → 模型决策调用 → 传参 → 执行 → 返回结果"。差异只在 schema 描述格式和传输协议，适配层做一次格式转译即可统一。而且 GNEX 的 `SandboxPort` 已经把"执行一个动作"统一了。

### 21.2 差异 2：上下文生命周期策略

| 框架 | 策略 |
|------|------|
| Claude 非 Fork | SubAgent 从零开始，主 Agent 要写详细 prompt 传递上下文 |
| Claude Fork | SubAgent 继承当前 context session |
| OpenClaw per-peer | 每个用户独立会话 |
| Hermes | 比例压缩（不新建会话，压缩头部+尾部+中间摘要） |

**结论**：❌ **不构成障碍**。上下文管理策略不是硬编码的，而是写在 Harness 编排逻辑里的。只要蒸馏颗粒度是"整个编排行为"（含上下文管理），策略就一并拿过来了。GNEX 的原语层通过 `session_create`（含 scope 参数）和 `session_compress`（含 strategy 参数）可以支持所有这些策略。

**前提条件**：蒸馏时必须完整提取编排逻辑，不能只提循环结构而漏掉上下文管理逻辑。

### 21.3 差异 3：安全/权限模型

| 框架 | 安全策略 |
|------|---------|
| Claude | 路径白名单 + 命令黑名单 + SubAgent 工具集限制 |
| OpenClaw | dmScope 隔离 + ChannelPlugin 安全策略 |
| Hermes | 四层防御（14 种错误分类 + 自愈策略 + 子 Agent 工具限制 + Skill 静态扫描） |

**结论**：❌ **不构成障碍**。安全和权限的"软"部分（在 Harness 里的规则）随整体蒸馏一并拿过来。GNEX 平台还有自己的"硬"安全层。

**两层安全模型**：

```
GNEX 平台层安全（硬编码，不可被覆盖）：
  ├─ 多租户隔离
  ├─ 网络出站白名单
  ├─ 沙箱资源配额（CPU/内存/超时）
  └─ 审计日志（所有行为必须记录）

Harness 层安全（蒸馏来的，随 Harness 走）：
  ├─ Claude 的工具约束
  ├─ Hermes 的四层防御
  └─ OpenClaw 的 Channel 策略

合并规则：平台层安全 ⊃ Harness 层安全
         Harness 的安全策略可以比平台更严格，但不能更宽松
         冲突时平台层优先
```

### 21.4 差异 4：记忆系统（唯一有实质挑战的差异）

| 框架 | 记忆范式 | 存储位置 | 数据形态 |
|------|---------|---------|---------|
| Claude | **静态注入** | AGENTS.md（文件） | 自由文本 |
| OpenClaw | **运行时状态** | Gateway 进程内 + Session | 结构化 Session 对象 |
| Hermes | **动态沉淀** | skills/（文件）+ Mem0（向量库）+ MEMORY.md | Skill 文件 + 向量 embedding |

**结论**：⚠️ **唯一有实质工程挑战的差异**。三种完全不同的记忆范式（静态注入 vs 运行时状态 vs 动态沉淀），不是简单的格式不同。

**解法**：通过 GNEX 的 `read` / `write` 原语 + `source` / `target` 的 URL scheme 统一所有存储类型，加上 `sub`（Hook 机制）覆盖 Hermes 的自动触发场景。具体见第 23 章和第 25 章。

**关键洞察**：记忆系统的差异最终被降维成"调用哪些原语 + 在什么时机调用"——而这些是写在 Harness 里的编排逻辑的一部分，随整体蒸馏一并拿过来了。

### 21.5 差异 5：消息报送方式

| 框架 | 报送方式 |
|------|---------|
| Claude | SubAgent 完成后返回一条文本；后台完成自动通知 |
| OpenClaw | Agent Loop 六阶段流转（intake→...→persist） |
| Hermes | 全生命周期 Hook（on_tool_call / on_session_end） |

**结论**：❌ **不构成障碍**。消息报送方式的差异被 `pub` / `sub` / `io` 三个原语覆盖。Claude 的后台通知 = `sub`；OpenClaw 的 persist = `write`；Hermes 的 Hook = `sub` + 回调任务。

### 21.6 五大差异总结

| 差异点 | 是否构成障碍 | 解法 |
|--------|-------------|------|
| 工具执行 | ❌ 不是障碍 | SandboxPort 已统一 |
| 上下文生命周期 | ❌ 不是障碍 | 整体蒸馏一并拿来，原语层支持多种策略 |
| 安全/权限 | ❌ 不是障碍 | 两层安全合并（平台 ⊃ Harness） |
| 记忆系统 | ⚠️ 需要扩展原语集 | read/write 的 URL scheme + sub 的 Hook 机制 |
| 消息报送 | ❌ 不是障碍 | pub/sub/io 三个原语覆盖 |

---

## 22. 适配器层架构：动态映射与复合操作

### 22.1 设计演进过程（三次认知升级）

讨论中经历了三次重要的认知升级，最终确定了当前的架构方案：

```
第一次（已否定）：翻译行为
  看对方框架的 Agent Loop 怎么跑 → 手写适配器模拟它的行为
  → 代码量大、容易出错、难维护

第二次（已否定）：原语编译 + 序列展开（AOT 静态编译）
  加载时把对方框架全量编译成 GNEX 原语格式
  → 问题1：LLM 的工具调用决策必须在运行时有完整上下文才能做，不可能预编译
  → 问题2：静态预编译如果某步出错，后面全错，错误级联放大无法纠正
  → 问题3：token 消耗没有减少（工具描述无论叫什么名字都一样占 token）

第三次（已否定）：运行时查表映射（JIT）
  保留对方工具名，运行时查映射表翻译
  → 问题：查表只解决简单的 1:1 映射（Bash→exec）
  → 复杂操作（如创建子 Agent）的动态参数组装、序列展开查表做不到
  → 需要理解语义才能正确映射

第四次 ★ 最终采用：动态映射 + 复合操作
  简单操作：LLM 在 System Prompt 的 Harness 说明引导下直接输出 GNEX 原语
  复杂操作：LLM 调用框架提供的复合操作名，框架代码确定性执行
  → 简单操作不需要查表（LLM 自己映射）
  → 复杂操作不需要 LLM 自己组装原语序列（框架脚本保证流程确定性）
  → 参数临时决定不影响流程稳定性（参数是数据流，脚本是控制流）
```

### 22.2 方案的核心机制

**两个层次协同工作：**

```
层次 1：简单操作 → LLM 自主映射（不需要查表）
  
  System Prompt 中注入 Harness 说明（自然语言，约 300-500 token）：
    "GNEX 原语与 Claude 能力的对应关系：
     执行命令 → exec(command=...)
     读取文件 → read(source='file://{path}', offset, limit)
     写入文件 → write(target='file://{path}', data, mode)
     ..."
  
  LLM 拿到这段说明 + 完整执行上下文后，
  直接输出 GNEX 原语调用：
    exec(command="ls -la")
  
  → 不需要查表，LLM 自己理解语义做了映射
  → 因为工具列表里就是 GNEX 原语名

层次 2：复杂操作 → 框架复合操作脚本（确定性执行）

  复杂操作（如创建子 Agent）由框架提供复合操作：
    spawn_agent(type, prompt, context_mode)
  
  LLM 只做一次决策（一次 function call）：
    "我要创建一个 Explore 类型的子 Agent"
    → spawn_agent(type="Explore", prompt="搜索deprecated", context_mode="fresh")
  
  框架代码接管，确定性执行内部流程：
    → pub(agent.created)
    → session_create
    → [think-act 循环：子 Agent 自己用 GNEX 原语]
    → pub(agent.completed)
  
  → 流程骨架由代码保证（100% 确定）
  → 具体内容由子 Agent 的 LLM 动态决策
  → 参数（type, prompt）临时填入不影响流程稳定性
```

### 22.3 适配器层在控制面中的位置

```
┌──────────────────────────────────────────────────────────────┐
│  控制面单体（模块化单体）                                      │
│                                                               │
│  ┌─ Harness Adapter Layer（适配器层）──────────────────────┐ │
│  │                                                          │ │
│  │  ┌─ Harness Profile（加载时）─────────────────────────┐ │ │
│  │  │  ├─ harness_description：Claude 能力→GNEX原语的说明 │ │ │
│  │  │  │  （自然语言，注入到 System Prompt，约 300-500 token）│ │
│  │  │  ├─ system_prompt_template：System Prompt 模板      │ │ │
│  │  │  │  （保留原始能力描述 + 追加 GNEX 平台规则）        │ │ │
│  │  │  └─ safety_rules：Harness 层安全策略                │ │ │
│  │  └────────────────────────────────────────────────────┘ │ │
│  │                                                          │ │
│  │  ┌─ 复合操作注册表（加载时）──────────────────────────┐ │ │
│  │  │  spawn_agent(type, prompt, context_mode)            │ │ │
│  │  │  compress_context(strategy, threshold)               │ │ │
│  │  │  generate_skill(content, metadata)                   │ │ │
│  │  │  handoff(to_agent, context_summary)                  │ │ │
│  │  │  → 每个复合操作是一个 Python 函数（脚本）             │ │ │
│  │  │  → 内部展开为 GNEX 原语序列                          │ │ │
│  │  │  → 流程骨架固定，参数动态填入                        │ │ │
│  │  └────────────────────────────────────────────────────┘ │ │
│  │                                                          │ │
│  │  运行时：LLM 自主输出 GNEX 原语调用                     │ │
│  │         或调用复合操作名（框架代码执行）                  │ │
│  │         不需要查表，不需要翻译                            │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─ GNEX 核心原语层（7 个原子原语 + 4 个复合操作）─────────┐ │
│  │                                                          │ │
│  │  原子原语（LLM 直接调用）：                              │ │
│  │    exec / read / write / llm / io / pub / sub           │ │
│  │                                                          │ │
│  │  复合操作（LLM 调用名字，框架代码展开）：                 │ │
│  │    spawn_agent / compress_context /                      │ │
│  │    generate_skill / handoff                              │ │
│  │                                                          │ │
│  │  所有原语和复合操作自动：                                │ │
│  │    权限检查 → 路由到正确沙箱/服务 → 审计 → 可观测        │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 22.4 工程维护模型

```
需要维护的东西：
├─ GNEX 核心原子原语（7 个，极稳定，几乎不变）
│
├─ 复合操作脚本（3-5 个，框架代码，稳定）
│   ├─ spawn_agent.py    → 内部展开为 pub + session_create + llm循环 + pub
│   ├─ compress_context.py → 内部展开为 llm(摘要) + write
│   ├─ generate_skill.py → 内部展开为 write + read
│   └─ handoff.py        → 内部展开为 pub + read + pub
│
├─ 每个框架的 Harness Profile（一个 YAML/自然语言文件）
│   ├─ claude_profile.yaml    → Claude 能力说明 + Prompt 模板
│   ├─ hermes_profile.yaml    → Hermes 能力说明 + Prompt 模板
│   └─ openclaw_profile.yaml  → OpenClaw 能力说明 + Prompt 模板
│
└─ 那就完了。

新增一个框架 = 写一个 Harness Profile（自然语言说明）
不需要改 GNEX 核心原语
不需要改复合操作脚本
不需要写代码级的映射表
```

### 22.4 多副本按需加载

不同框架的 Harness 可以作为控制面的不同实例副本运行：

**方案 A：配置化加载（推荐起步）**

```yaml
# config/harness-profiles/claude-style.yaml
profile_name: claude-style
mapping_table: claude_mapping.yaml
description: "Claude Code 风格的编排，强控制、SubAgent 隔离"

# config/harness-profiles/hermes-style.yaml
profile_name: hermes-style
mapping_table: hermes_mapping.yaml
description: "Hermes 风格的编排，自进化、动态 Skill 沉淀"

# config/harness-profiles/gnex-hybrid.yaml
profile_name: gnex-hybrid
mapping_table: gnex_hybrid_mapping.yaml
description: "GNEX 混搭风格，取各家之长"
```

```bash
# 同一个镜像，启动时按配置加载不同 Harness Profile
CONTROL_PLANE_HARNESS_PROFILE=claude-style ./agent-os-server
CONTROL_PLANE_HARNESS_PROFILE=hermes-style ./agent-os-server
```

**方案 B：多镜像（未来规模化）**

```
镜像：
├─ agent-os:claude-style-v1.0
├─ agent-os:hermes-style-v1.0
└─ agent-os:gnex-hybrid-v1.0

K8s 部署：
├─ Deployment "cp-claude-style" (replicas=5)
├─ Deployment "cp-hermes-style" (replicas=3)
└─ Deployment "cp-gnex-hybrid" (replicas=10)
```

### 22.5 Harness Router（编排风格路由器）

调度器根据任务类型路由到不同风格的副本：

```
用户请求 → Harness Router
             ├─ 代码任务 → claude-style（SubAgent 强）
             ├─ 多渠道客服 → openclaw-style（路由强）
             ├─ 需要持续学习 → hermes-style（进化强）
             └─ 默认 → gnex-hybrid
```

---

## 23. 核心原语集定义（7 个原子原语 + 4 个复合操作）

### 23.1 原语的设计原则

**原则 1：原语是 GNEX 框架唯一认的"货币"**

任何 Harness 的编排行为，最终都被翻译成原语的调用序列。GNEX 不认 Claude 的 Tool Call，不认 Hermes 的 Skill，不认 OpenClaw 的 Agent Loop——GNEX 只认原语。

**原则 2：所有原语是 async 的，返回标准结果对象**

```python
result = await primitive(...)
# result.status: "success" | "error" | "timeout"
# result.data: 原语返回的数据
# result.error: 错误信息（如果失败）
# result.metadata: 执行元数据（耗时、资源消耗、审计标记）
```

**原则 3：每个原语自带审计标记**

每个原语调用都隐式产生一条审计记录。这不是原语使用者要做的，是框架在原语执行层自动插入的。这样不管跑什么 Harness，审计能力都天然具备。

**原则 4：原语越少越好，能够复用的就尽量不要额外出新原语**

原语过多会导致编排稳定性变差，维护成本上升。核心原语应保持极简和稳定。

### 23.2 为什么是 7 个（从 36 个精简到 7 个的过程）

讨论中经历了重要的精简过程。初始方案定义了 36 个原语（6 个域），但审查后发现大部分根本不是原语，是复合操作：

```
❌ 错误地列为"原语"的复合操作：
   agent_invoke  = session_create + llm_call × N + exec/read/write × N + session_merge
   session_compress = llm_call(摘要) + session_update
   memory_search = embed(text) + similarity_query
   agent_handoff = context_transfer + agent_switch

✅ 真正不可再分的操作只有 7 个
```

### 23.3 七个核心原语

```python
# ============================================================
# GNEX 核心原语集（7 个，不可再减）
# ============================================================

# ┌─ 执行 ─────────────────────────────────────────────┐
# │
async def exec(
    session_id: str,
    command: str,
    timeout: int = 300,          # 秒
    workdir: str = "/workspace",
) -> Result:
    """在沙箱里执行 shell 命令
    
    所有框架的"执行类"操作最终都映射到这里：
    - Claude 的 Bash 工具 → exec(command)
    - OpenClaw 的 pi_bash → exec(command)
    - Hermes 的 exec 工具 → exec(command)
    - Claude 的 Grep → exec("grep -rn ...")
    - Claude 的 Glob → exec("find . -name ...")
    """
    ...

# │
# ├─ 读 ───────────────────────────────────────────────┤
# │
async def read(
    session_id: str,
    source: str,                 # URL scheme 标识来源（见第 25 章）
    **options                    # 结构化附加参数
) -> Result:
    """从某个位置读数据
    
    通过 source 的 URL scheme 统一所有存储类型：
    - read(source="file:///workspace/src/main.py")     → 读文件
    - read(source="kv://session_123/context")          → 读 KV
    - read(source="vector://mem0?query=偏好")           → 向量检索
    - read(source="file:///skills/", list_mode=True)   → 列目录
    
    所有框架的"读取类"操作最终都映射到这里：
    - Claude 的 Read → read(source="file://{path}")
    - Hermes 的 memory_read → read(source="file://MEMORY.md")
    - Hermes 的 mem0_search → read(source="vector://mem0", query=...)
    - OpenClaw 的 session_restore → read(source="kv://session:{key}")
    """
    ...

# │
# ├─ 写 ───────────────────────────────────────────────┤
# │
async def write(
    session_id: str,
    target: str,                 # URL scheme 标识目标（见第 25 章）
    data: str = None,            # 要写入的内容
    mode: str = "overwrite",     # "overwrite" | "append"
    **options                    # 结构化附加参数（如 patch、metadata、embed）
) -> Result:
    """向某个位置写数据
    
    通过 target 的 URL scheme 统一所有存储类型：
    - write(target="file:///output.txt", data="...")          → 写文件
    - write(target="kv://session_123/progress", data="step5") → 写 KV
    - write(target="vector://mem0", data="...", embed=True)   → 写向量
    - write(target="file:///main.py", patch={old,new})        → 编辑文件
    
    所有框架的"写入类"操作最终都映射到这里：
    - Claude 的 Write → write(target="file://{path}", data=content)
    - Claude 的 Edit → write(target="file://{path}", patch={old_str, new_str})
    - Hermes 的 skill_generate → write(target="file://~/.hermes/skills/{name}")
    - OpenClaw 的 session_persist → write(target="kv://session:{key}")
    """
    ...

# │
# ├─ 推理 ─────────────────────────────────────────────┤
# │
async def llm(
    session_id: str,
    model: str,                  # 模型标识
    messages: list,              # 对话历史
    tools: list = None,          # 可用工具 schema
    temperature: float = 0.0,
    max_tokens: int = 4096,
    system_prompt: str = None,
    stream: bool = False,        # True 时返回 AsyncIterator
) -> Result:
    """调用 LLM API
    
    所有框架的"思考"步骤最终都映射到这里。
    底层可对接 LiteLLM / OpenRouter / 直连 API。
    
    Claude/Hermes/OpenClaw 的模型推理 → llm(model, messages, tools)
    """
    ...

# │
# ├─ 通信（同步） ─────────────────────────────────────┤
# │
async def io(
    session_id: str,
    protocol: str,               # "http" | "https" | "mcp" | "websocket"
    endpoint: str,               # 目标地址
    method: str = "GET",         # HTTP 方法
    headers: dict = None,
    body: str = None,
    timeout: int = 30,
) -> Result:
    """同步外部通信（请求-响应模式）
    
    - Claude 的 WebFetch → io(protocol="http", endpoint=url)
    - Claude 的 WebSearch → io(protocol="http", endpoint=search_api)
    - Hermes 的 http_request → io(protocol="http", endpoint=url)
    - 任何 MCP Server 调用 → io(protocol="mcp", endpoint=mcp_server)
    """
    ...

# │
# ├─ 发布事件（异步广播）──────────────────────────────┤
# │
async def pub(
    session_id: str,
    topic: str,                  # 事件主题
    payload: dict,               # 事件内容
) -> Result:
    """向事件流发布一条消息（不等响应）
    
    用于 Agent 间异步通信、审计事件、黑板模式。
    
    - Claude 的后台 Agent 完成通知 → pub(topic="agent.{id}.completed")
    - OpenClaw 的 EventStream → pub(topic="channel.{id}")
    - 黑板模式的字段更新 → pub(topic="blackboard.{field}")
    """
    ...

# │
# └─ 订阅事件（异步监听）──────────────────────────────┘
async def sub(
    session_id: str,
    topic: str,                  # 订阅的主题
    handler: str,                # 收到事件后执行的 agent 任务描述
) -> Result:
    """订阅一个事件主题
    
    用于接收异步通知、生命周期 Hook。
    
    - Hermes 的 on_session_end → sub(topic="session.{id}.ended", handler="审查并生成Skill")
    - Hermes 的 on_tool_call → sub(topic="tool.{id}.before", handler="参数校验")
    - Claude 的后台 Agent 通知接收 → sub(topic="agent.{id}.completed")
    - 黑板模式的字段监听 → sub(topic="blackboard.{field}", handler="处理变化")
    """
    ...
```

### 23.4 横切关注点（自动插入，不需显式调用）

安全/权限不作为独立原语域。它是 GNEX 平台的横切关注点，由框架在原语执行层自动插入检查：

```
每个原语执行时自动经过的管线：

原语调用 → [权限检查] → [多租户隔离校验] → [安全策略合并] → 执行 → [审计记录] → [可观测事件] → 返回
```

### 23.5 复合操作（框架脚本，确定性执行）

**为什么需要复合操作？**

7 个原子原语能覆盖所有底层操作，但有些操作是"流程固定、内容动态"的——如果让 LLM 自己用原子原语组装这些流程，会引入三个问题：

1. **多轮调用开销**：一个"创建子 Agent"操作需要 5-8 轮 LLM 调用，而不是 1 次
2. **上下文膨胀**：所有中间步骤都进入主 Agent 的上下文，违背上下文隔离的初衷
3. **执行不确定性**：LLM 可能遗漏步骤（忘记创建独立上下文、忘记回传结果），5% 的错误率在企业场景不可接受

**复合操作 = 框架用代码写的原语序列脚本，流程骨架 100% 确定，参数动态填入。**

每个复合操作本质上是一个"小的 ReAct 循环"——它有自己的编排流程，内部也会调 LLM，但骨架由代码保证。

```python
# ============================================================
# GNEX 复合操作集（4 个，框架代码提供）
# ============================================================

# ┌─ spawn_agent ──────────────────────────────────────┐
# │  创建并启动一个子 Agent（类似操作系统的 fork()）
# │
# │  内部展开为：
# │    pub(agent.created)
# │    → session_create(scope) 或 session_fork()
# │    → [think-act 循环：子 Agent 用 GNEX 原语执行]
# │    → pub(agent.completed)
# │
# │  对应第三方框架：
# │    Claude 的 Agent 工具 → spawn_agent
# │    OpenClaw 的 run_pi_agent → spawn_agent
# │    Hermes 的内嵌调用 → spawn_agent
# └──────────────────────────────────────────────────────┘
async def spawn_agent(
    agent_type: str,             # 子 Agent 类型
    prompt: str,                 # 给子 Agent 的任务
    context_mode: str = "fresh", # "fresh" | "fork" | "inherit"
    tools: list = None,          # 子 Agent 可用的工具
    model: str = None,           # 子 Agent 用的模型
) -> Result:
    """创建并执行子 Agent

    脚本保证的（控制流确定性）：
      ✓ 每次都先发 pub 事件
      ✓ 每次都正确创建独立上下文
      ✓ 每次循环都检查退出条件
      ✓ 每次结果都正确回传
      ✓ 每次都禁止嵌套（如果规则要求）

    脚本不保证的（数据流动态性）：
      ✗ 子 Agent 在循环内调什么工具（LLM 决定）
      ✗ 循环几轮（任务复杂度决定）
      ✗ 最终结果内容（LLM 生成）
    """
    ...

# ┌─ compress_context ─────────────────────────────────┐
# │  压缩会话上下文
# │
# │  内部展开为：
# │    llm(model, messages=[{system:"摘要这些对话"}, {user:历史}])
# │    → write(kv://session/context, 摘要结果)
# │
# │  对应第三方框架：
# │    Hermes 的比例压缩 → compress_context(strategy="ratio")
# │    OpenClaw 的固定阈值 → compress_context(strategy="fixed")
# └──────────────────────────────────────────────────────┘
async def compress_context(
    session_id: str,
    strategy: str = "ratio",      # "ratio" | "fixed" | "summarize" | "truncate"
    threshold: float = 0.5,       # 触发阈值
) -> Result:
    """压缩会话上下文（框架代码执行，不依赖 LLM 自己组装）"""
    ...

# ┌─ generate_skill ───────────────────────────────────┐
# │  生成并保存 Skill（对应 Hermes 的自进化能力）
# │
# │  内部展开为：
# │    llm(model, messages=[{system:"审查会话并生成Skill"}, ...])
# │    → write(file://~/.hermes/skills/{name}, skill_content)
# │    → read(file://~/.hermes/skills/, list_mode=True)  # 刷新列表
# │
# │  对应第三方框架：
# │    Hermes 的 Skill 自动生成 → generate_skill
# └──────────────────────────────────────────────────────┘
async def generate_skill(
    session_id: str,
    skill_name: str,
    review_prompt: str = None,    # 审查提示（可选）
) -> Result:
    """生成并保存 Skill（框架代码执行审查+写入流程）"""
    ...

# ┌─ handoff ──────────────────────────────────────────┐
# │  控制权交接（对应 Swarm/Claude 的 handoff 机制）
# │
# │  内部展开为：
# │    read(kv://session/context)  # 读当前上下文
# │    → pub(topic="agent.handoff", payload={context, to_agent})
# │    → 目标 Agent 接管
# │
# │  对应第三方框架：
# │    OpenAI Swarm 的 handoff → handoff
# │    Claude 的 transfer_to_agent → handoff
# └──────────────────────────────────────────────────────┘
async def handoff(
    from_agent_id: str,
    to_agent_id: str,
    context_summary: str = None,
) -> Result:
    """控制权交接（框架代码执行上下文传递）"""
    ...
```

### 23.6 原子原语与复合操作的分工

| 维度 | 原子原语（7 个） | 复合操作（4 个） |
|------|-----------------|-----------------|
| **谁组装序列** | LLM 自己决定调什么 | 框架代码固定序列 |
| **流程确定性** | 完全由 LLM 决定 | 骨架固定，内容动态 |
| **适合的操作** | 流程和内容都动态（搜索/读取/执行） | 流程固定但内容动态（创建子Agent/压缩/Skill生成） |
| **调用方式** | LLM 直接输出原语名 | LLM 输出复合操作名，框架展开 |
| **LLM 调用次数** | 每次 1 次（原子操作） | 外层 1 次 + 内层多轮（子 Agent 循环） |

**设计原则**：凡是"流程固定、内容动态"的操作，用复合操作（框架保证骨架）；凡是"流程和内容都动态"的操作，用原子原语（LLM 自己决策）。

---

## 24. io 与 pub/sub 的独立性分析

### 24.1 三者的本质语义差异

| 原语 | 通信模式 | 时序 | 调用方知道处理方吗 | 适合场景 |
|------|---------|------|:------------------:|---------|
| **io** | 点对点请求-响应 | 同步阻塞 | ✅ 知道 endpoint | 需要确定的返回值才能继续 |
| **pub** | 发布到主题 | 完全异步 | ❌ 只发 topic | 通知、广播、解耦 |
| **sub** | 监听主题 | 完全异步 | ❌ 只消费事件 | 接收通知、Hook 机制 |

### 24.2 为什么不合并

**结论：不合并。保持 3 个独立原语。**

理由：

1. **语义模糊导致编排混乱**：合并后，适配器开发者看到 `io()` 时不知道是同步等响应还是异步发事件。这种不确定性在编排逻辑里是危险的。

2. **路由机制完全不同**：
   - `io` 的路由：调用方 → 明确 endpoint → HTTP/gRPC client
   - `pub`/`sub` 的路由：发布方 → topic → 消息总线 → 未知数量的订阅者
   - 合并后框架内部要用 if-else 判断走不同路由，违反原语"不可再分"原则

3. **可观测性不同**：
   - `io` 的审计：调用方、被调用方、请求/响应体、延迟、状态码（类似 HTTP APM）
   - `pub`/`sub` 的审计：发布方、topic、payload、消费者列表、消费延迟（类似消息队列监控）

> **D010：io / pub / sub 保持独立，不合并。三者通信语义根本不同（同步点对点 / 异步广播 / 异步监听）。**

### 24.3 llm 是否并入 io

**结论：不并入。** 虽然技术上 `llm` 就是调一个 HTTP API，但：
1. 执行语义不同：`exec` 在沙箱里跑，`llm` 在控制面直接调 API
2. 审计需求不同：`llm` 要单独审计（token 消耗、成本、模型版本）
3. 优化空间不同：`llm` 可以做缓存、降级、负载均衡

---

## 25. read/write 的 source/target 格式设计

### 25.1 格式规范：URL scheme + 结构化 options

```python
# 格式：协议://路径?查询参数
# 配合 **options 传结构化附加参数

read(source="file:///workspace/src/main.py")
read(source="kv://session_123/context")
read(source="vector://mem0/users?query=偏好&top_k=5")
```

**为什么用 URL scheme**：
- 人眼可读，YAML 配置友好
- 协议前缀天然标识存储类型
- 查询参数支持过滤条件
- 未来扩展新存储类型只需加新协议前缀

**为什么配 options 参数**：
- URL 里塞结构化数据（如 patch、metadata）很丑且需 URL encode
- options 传结构化参数更灵活、更清晰

### 25.2 支持的协议前缀

| 协议 | 存储类型 | read 能力 | write 能力 |
|------|---------|----------|-----------|
| `file://` | 沙箱文件系统 | 文件内容 / 目录列表 | 覆盖 / 追加 / 搜索替换 |
| `kv://` | Redis（热状态、会话状态） | 按 key 查询 | 按 key 写入，支持 TTL |
| `vector://` | 向量数据库（Mem0/Milvus/Qdrant） | 语义检索（query + top_k） | 写入并自动 embed |
| `graph://` | 图数据库（未来扩展） | 图查询 | 节点/边写入 |
| `blob://` | 对象存储（S3/MinIO） | 下载大文件 | 上传大文件 |
| `stream://` | 流式数据（未来扩展） | 从流中读 | 向流中写 |

### 25.3 完整用法示例

```python
# ============================================================
# read 的用法
# ============================================================

# 文件读取
await read(session_id="s1", source="file:///workspace/src/main.py")

# 文件读取（带行范围，对应 Claude 的 Read offset/limit）
await read(session_id="s1", source="file:///workspace/src/main.py",
           offset=10, limit=100)

# KV 读取
await read(session_id="s1", source="kv://session_123/context")

# KV 读取（带 key 过滤）
await read(session_id="s1", source="kv://session_123/memory", key="user_pref")

# 向量检索（对应 Hermes 的 mem0_search）
await read(session_id="s1", source="vector://mem0/users",
           query="用户偏好的编程语言", top_k=5, score_threshold=0.7)

# 目录列表（对应 Claude 的 Glob / Hermes 的 skill_list）
await read(session_id="s1", source="file:///workspace/src/",
           list_mode=True, pattern="**/*.py")

# ============================================================
# write 的用法
# ============================================================

# 文件覆盖（对应 Claude 的 Write）
await write(session_id="s1", target="file:///workspace/output.txt",
            data="新的内容", mode="overwrite")

# 文件追加
await write(session_id="s1", target="file:///workspace/log.txt",
            data="新的一行\n", mode="append")

# 文件编辑（对应 Claude 的 Edit / OpenClaw 的 edit）
await write(session_id="s1", target="file:///workspace/src/main.py",
            patch={"old_str": "print('hello')", "new_str": "print('world')"})

# KV 写入（对应 OpenClaw 的 session_persist）
await write(session_id="s1", target="kv://session_123/progress",
            data="step_5_completed", ttl=3600)

# 向量写入（对应 Hermes 的 memory_write + embed）
await write(session_id="s1", target="vector://mem0/users",
            data="用户擅长 Python 后端开发",
            metadata={"source": "skill_review", "timestamp": "2026-06-15"},
            embed=True)

# Skill 文件写入（对应 Hermes 的 skill_generate）
await write(session_id="s1",
            target="file:///home/.hermes/skills/code_review.md",
            data="<skill content>",
            metadata={"skill_name": "code_review", "auto_generated": True})
```

### 25.4 框架内部的路由逻辑

```
read(source="file://...")  → 权限检查 → 路由到沙箱文件系统 → 读取
read(source="kv://...")    → 权限检查 → 路由到 Redis → 查询
read(source="vector://...") → 权限检查 → 路由到向量数据库 → 检索

write(target="file://...") → 权限检查 → 安全策略合并 → 路由到沙箱文件系统 → 写入
write(target="kv://...")   → 权限检查 → 路由到 Redis → 写入
write(target="vector://...", embed=True)
                          → 权限检查 → 生成 embedding → 路由到向量数据库 → 写入
```

---

## 26. 框架映射表与编译规则

### 26.1 映射表的作用

映射表是适配器的核心——声明式地定义"第三方框架的原语"如何对应到"GNEX 的原语或原语序列"。

映射分两类：
- **直接映射**：对方原语一对一映射到某个 GNEX 原语
- **序列展开**：对方原语需要展开成多个 GNEX 原语的序列

### 26.2 Claude Code 映射表

```yaml
# claude_mapping.yaml
framework: claude-code
version: 2.1.x

mappings:
  # ── 直接映射 ──
  Bash:
    gnex_primitive: exec
    params:
      command: "$command"

  Read:
    gnex_primitive: read
    params:
      source: "file://{path}"
      offset: "$offset"
      limit: "$limit"

  Write:
    gnex_primitive: write
    params:
      target: "file://{path}"
      data: "$content"
      mode: "overwrite"

  Edit:
    gnex_primitive: write
    params:
      target: "file://{path}"
      patch:
        old_str: "$old_str"
        new_str: "$new_str"

  Grep:
    gnex_primitive: exec
    params:
      command: "grep -rn '{pattern}' {path}"

  Glob:
    gnex_primitive: read
    params:
      source: "file://{path}"
      list_mode: true
      pattern: "$pattern"

  WebSearch:
    gnex_primitive: io
    params:
      protocol: "http"
      endpoint: "${SEARCH_API}"
      params:
        q: "$query"

  WebFetch:
    gnex_primitive: io
    params:
      protocol: "http"
      endpoint: "$url"

  # ── 序列展开 ──
  Agent:
    type: sequence
    description: "SubAgent 调用展开为原语序列"
    steps:
      - primitive: pub
        params:
          topic: "agent.created"
          payload:
            type: "$subagent_type"
            parent: "$caller"
      - primitive: llm
        params:
          model: "$model"
          messages:
            - role: "system"
              content: "$subagent_system_prompt"
            - role: "user"
              content: "$prompt"
          tools: "$subagent_tools"
      # 后续进入 think-act 循环，由编排逻辑驱动
      - type: loop
        condition: "has_tool_call"
        steps:
          - primitive: "tool_dispatch"  # 根据 LLM 返回的工具调用，路由到 exec/read/write/io
          - primitive: llm
            params:
              messages: "$messages_with_tool_result"
      - primitive: pub
        params:
          topic: "agent.completed"
          payload:
            result: "$final_result"

  SendMessage:
    type: sequence
    description: "向已运行/已完成的 Agent 发消息"
    steps:
      - primitive: pub
        params:
          topic: "agent.{agent_id}.message"
          payload:
            message: "$message"

  # ── 上下文管理 ──
  context_mode:
    non_fork: "fresh"     # SubAgent 从零开始
    fork: "fork"           # SubAgent 继承父 Agent 上下文
```

### 26.3 Hermes 映射表

```yaml
# hermes_mapping.yaml
framework: hermes-agent
version: 0.16.x

mappings:
  # ── 直接映射 ──
  exec:
    gnex_primitive: exec
    params:
      command: "$command"

  read_file:
    gnex_primitive: read
    params:
      source: "file://{path}"

  write_file:
    gnex_primitive: write
    params:
      target: "file://{path}"
      data: "$data"

  http_request:
    gnex_primitive: io
    params:
      protocol: "http"
      endpoint: "$url"

  llm_call:
    gnex_primitive: llm
    params:
      model: "$model"
      messages: "$messages"

  # ── 记忆系统映射 ──
  memory_read:
    gnex_primitive: read
    params:
      source: "file:///MEMORY.md"

  memory_write:
    gnex_primitive: write
    params:
      target: "kv://memory/{key}"
      data: "$value"

  mem0_search:
    gnex_primitive: read
    params:
      source: "vector://mem0"
      query: "$query"
      top_k: 5

  # ── Skill 系统 ──
  skill_list:
    gnex_primitive: read
    params:
      source: "file://~/.hermes/skills/"
      list_mode: true

  skill_generate:
    gnex_primitive: write
    params:
      target: "file://~/.hermes/skills/{name}"
      data: "$skill_content"
      metadata:
        auto_generated: true

  # ── Hook 机制 ──
  hook_on_session_end:
    gnex_primitive: sub
    params:
      topic: "session.{session_id}.ended"
      handler: "$callback"

  hook_on_tool_call:
    gnex_primitive: sub
    params:
      topic: "tool.{session_id}.before"
      handler: "$callback"

  hook_on_memory_write:
    gnex_primitive: sub
    params:
      topic: "memory.{session_id}.write"
      handler: "$callback"
```

### 26.4 OpenClaw 映射表

```yaml
# openclaw_mapping.yaml
framework: openclaw
version: 2026.6.x

mappings:
  # ── 四个原子工具 ──
  pi_read:
    gnex_primitive: read
    params:
      source: "file://{path}"

  pi_write:
    gnex_primitive: write
    params:
      target: "file://{path}"
      data: "$data"

  pi_edit:
    gnex_primitive: write
    params:
      target: "file://{path}"
      patch:
        old_str: "$old"
        new_str: "$new"

  pi_bash:
    gnex_primitive: exec
    params:
      command: "$command"

  # ── 会话管理 ──
  session_persist:
    gnex_primitive: write
    params:
      target: "kv://session:{key}"
      data: "$state"

  session_restore:
    gnex_primitive: read
    params:
      source: "kv://session:{key}"

  # ── 渠道路由 ──
  channel_route:
    gnex_primitive: pub
    params:
      topic: "channel.{channel_id}"
      payload: "$message"

  channel_subscribe:
    gnex_primitive: sub
    params:
      topic: "channel.{channel_id}"
      handler: "$agent_handler"

  # ── Agent 执行（序列）──
  run_pi_agent:
    type: sequence
    description: "Agent Loop 六阶段"
    steps:
      - name: intake
        primitive: read
        params:
          source: "kv://session:{key}/messages"
      - name: context_assembly
        primitive: llm
        params:
          model: "$model"
          messages: "$messages"
          tools: "$tools"
      - name: tool_execution
        type: conditional
        condition: "has_tool_call"
        steps:
          - primitive: exec  # 或 read/write/io，取决于工具类型
      - name: streaming_replies
        primitive: pub
        params:
          topic: "session.{session_id}.streaming"
          payload: "$chunk"
      - name: persistence
        primitive: write
        params:
          target: "kv://session:{key}"
          data: "$updated_state"
```

### 26.5 运行时映射流程

```
运行时的完整执行流程（每一轮 think-act）：

━━━ 准备阶段（加载时一次性完成）━━━━━━━━━━━━━━━━━

1. 加载 Harness Profile
   → 读取 claude_profile.yaml（自然语言能力说明 + Prompt 模板）

2. 构建 System Prompt
   → GNEX 平台规则 + GNEX 原语列表（7 原子 + 4 复合）+ Harness 说明
   → 这段说明告诉 LLM：Claude 的能力怎么对应到 GNEX 原语

3. 注册复合操作
   → spawn_agent / compress_context / generate_skill / handoff
   → 每个复合操作是一个 Python 函数，流程骨架固定

4. 构建工具列表
   → 给 LLM 的 tools 参数 = 7 个原子原语 + 4 个复合操作
   → 每个 tool 有完整的 JSON Schema 定义

━━━ 运行阶段（每轮 think-act）━━━━━━━━━━━━━━━━━━

5. LLM 调用（带完整上下文）
   输入：System Prompt + 消息上下文 + 工具列表
   LLM 自己理解 Harness 说明 + 当前任务 → 做决策

6. LLM 输出（两种情况）：

   情况 A：简单操作
     LLM 直接输出 GNEX 原语：
       "调用 exec(command='ls -la')"
     → 不需要查表，LLM 自己映射了
     → 直接执行 → 权限检查 → 沙箱 → 审计 → 返回

   情况 B：复杂操作
     LLM 输出复合操作名：
       "调用 spawn_agent(type='Explore', prompt='搜索deprecated')"
     → 框架代码接管
     → spawn_agent 脚本确定性执行：
         pub(agent.created)
         session_create(scope="per_agent")
         [子 Agent think-act 循环]
         pub(agent.completed)
     → 每个内部步骤都经过权限检查和审计

7. 结果回传
   → 执行结果加入 messages
   → LLM 在下一轮看到结果，继续决策

━━━ 映射的准确性保障 ━━━━━━━━━━━━━━━━━━━━━━━━━━━

为什么映射准确？
  ├─ LLM 拿到的是 GNEX 原语的完整描述 + Harness 说明
  ├─ LLM 理解语义（exec 和 Bash 都是"执行命令"）
  ├─ LLM 有完整的执行上下文做决策
  └─ 如果映射偶尔出错，LLM 下一轮看到错误结果会自我纠正

为什么不需要查表？
  ├─ 工具列表里直接是 GNEX 原语名
  ├─ LLM 不输出 "Bash"，直接输出 "exec"
  └─ 因为 System Prompt 里的 Harness 说明已经告诉它对应关系

为什么复合操作更安全？
  ├─ 流程骨架由 Python 代码保证（确定性 100%）
  ├─ LLM 只需决策"要不要做这件事"（1 次 function call）
  └─ 不需要 LLM 自己组装原语序列（避免遗漏步骤）
```

### 26.6 新增框架的工程流程

```
步骤 1：分析新框架的原语清单
  └─ 这个框架有哪些内置工具/操作？

步骤 2：写映射表
  └─ 每个原语对应到哪个 GNEX 原语？
  └─ 复合操作需要序列展开吗？

步骤 3：写 Harness Profile（YAML 配置）
  └─ 声明这个框架的编排风格

步骤 4：测试
  └─ 用新框架的典型任务跑一遍，验证原语序列正确

不需要做：
  ❌ 改 GNEX 核心原语
  ❌ 改 GNEX 框架代码
  ❌ 改新框架的代码
```

---

## 新增决策记录

| 编号 | 决策 | 理由 | 日期 |
|------|------|------|------|
| D009 | 选择原语蒸馏与编译路线（路线 C），放弃黑盒和半黑盒方案 | 企业应用必须保证可观测性和可控性，不可能接受黑盒或半黑盒状态 | 2026-06-16 |
| D010 | io / pub / sub 保持独立原语，不合并 | 三者通信语义根本不同（同步点对点 / 异步广播 / 异步监听），合并造成语义模糊 | 2026-06-16 |
| D011 | 核心原子原语集精简为 7 个（exec/read/write/llm/io/pub/sub） | 原语越少越稳定，36 个原语中大部分是复合操作不是真原语 | 2026-06-16 |
| D012 | read/write 通过 source/target 的 URL scheme 统一所有存储类型 | 一个原语覆盖文件/KV/向量/图/Blob 五种存储，避免原语膨胀 | 2026-06-16 |
| D013 | 适配器采用"动态映射 + 复合操作"模式，否定 AOT 静态编译和 JIT 查表 | LLM 决策必须运行时有完整上下文；查表无法处理复杂操作的动态参数；复合操作脚本保证流程确定性 | 2026-06-16 |
| D014 | 安全/权限作为横切关注点自动插入，不作为独立原语域 | 安全检查不是 Harness 编排逻辑的一部分，是平台级强制要求 | 2026-06-16 |
| D015 | llm 不并入 io，保持独立原语 | 执行路径、审计需求、优化策略都不同 | 2026-06-16 |
| D016 | 新增框架只需写 Harness Profile（自然语言说明），不改核心原语和框架代码 | 保证核心极稳定，扩展成本极低 | 2026-06-16 |
| D017 | 复杂操作（创建子Agent/上下文压缩/Skill生成/控制权交接）使用复合操作脚本，不让 LLM 自己组装原语序列 | 避免 LLM 组装序列时的多轮调用开销、上下文膨胀、执行不确定性（5% 错误率不可接受） | 2026-06-16 |
| D018 | 简单操作（执行/读写/搜索）由 LLM 在 System Prompt 引导下直接输出 GNEX 原语，不需要查表 | LLM 理解语义后自主映射，比查表更灵活；额外开销仅约 300-500 token 的 Harness 说明（占比 <0.4%） | 2026-06-16 |

---

## 新增术语

| 术语 | 定义 |
|------|------|
| **Harness Core（编排内核）** | 框架的编排哲学精华（循环模式/上下文策略/协作模式/安全护栏/Hook），是 GNEX 蒸馏的目标 |
| **Harness Adapter Layer（适配器层）** | 控制面内的模块，负责加载 Harness Profile、注册复合操作、构建 System Prompt |
| **原子原语（Atomic Primitive）** | 不可再分的底层操作（exec/read/write/llm/io/pub/sub），LLM 直接调用 |
| **复合操作（Composite Operation）** | 框架用代码写的原语序列脚本，流程骨架 100% 确定，参数动态填入。本质上是嵌套的小 ReAct 循环 |
| **动态映射（Dynamic Mapping）** | LLM 在运行时通过 System Prompt 中的 Harness 说明，自主将第三方框架的能力映射到 GNEX 原语，不需要查表 |
| **Harness Profile** | 一个 YAML/自然语言文件，声明第三方框架的能力说明和 System Prompt 模板，注入到运行时给 LLM 参考 |
| **Harness Router** | 根据任务类型路由到不同 Harness 风格副本的调度组件 |
| **三层嵌套 ReAct** | GNEX 的分层编排结构：大 Agent Loop（框架控制）→ 复合操作（脚本控制的小 ReAct）→ 原子原语（纯执行） |
| **source/target URL scheme** | read/write 原语用 URL 前缀（file://, kv://, vector://）标识存储类型 |
| **控制流确定性** | 复合操作脚本保证的执行流程稳定性（每步顺序固定），不受参数值变化影响 |
| **数据流动态性** | 参数值由 LLM 运行时临时决定，填入复合操作脚本的对应位置，不影响控制流 |

---

## 27. 三层嵌套 ReAct 结构

### 27.1 核心概念

GNEX 的编排架构本质上是**嵌套的 ReAct（Reasoning + Acting）结构**。每一层都把"控制流确定性"和"数据流灵活性"分离：

```
层级             控制者          控制什么              有 think 吗    类比
──────────────────────────────────────────────────────────────────────────
大 Agent Loop    GNEX 框架      整个任务的编排         有（LLM决策）   操作系统进程
复合操作         脚本（代码）    子流程的骨架           有（内层LLM）  操作系统线程
原子原语         框架执行层      单次执行               无（纯执行）    函数调用
```

### 27.2 三层结构的完整视图

```
┌──────────────────────────────────────────────────────────────┐
│  第一层：大 Agent Loop（大 ReAct）                              │
│  控制者：GNEX 框架                                              │
│                                                               │
│  while not done:                                              │
│      decision = llm(messages, tools)        ← 思考            │
│      if decision.is_simple_tool:                               │
│          result = exec / read / write / io / pub / sub       │
│          │   ← 直接执行原子原语，进入第三层                    │
│      elif decision.is_composite:                              │
│          result = spawn_agent(...) or compress_context(...)   │
│          │   ← 调用复合操作，进入第二层                        │
│      messages.append(result)                 ← 观察            │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│  第二层：复合操作（小 ReAct）                                   │
│  控制者：框架代码（脚本）                                       │
│                                                               │
│  以 spawn_agent 为例：                                         │
│                                                               │
│  def spawn_agent(type, prompt, context_mode):                 │
│      pub(topic="agent.created")             ← 固定步骤         │
│      session = session_create(scope=...)    ← 固定步骤         │
│                                                               │
│      while not done:                        ← 内层 think-act  │
│          decision = llm(messages, tools)    ← 子Agent思考      │
│          result = exec/read/write(...)      ← 子Agent行动      │
│          messages.append(result)            ← 子Agent观察      │
│                                                               │
│      pub(topic="agent.completed")           ← 固定步骤         │
│      return result                                            │
│                                                               │
│  脚本固定的（控制流）：                                         │
│    ✓ 每次都先发 pub 事件                                       │
│    ✓ 每次都正确创建独立上下文                                   │
│    ✓ 每次循环都检查退出条件                                     │
│    ✓ 每次结果都正确回传                                         │
│                                                               │
│  脚本不固定的（数据流）：                                       │
│    ✗ 子 Agent 在循环内调什么工具（LLM 决定）                    │
│    ✗ 循环几轮（任务复杂度决定）                                 │
│    ✗ 最终结果内容（LLM 生成）                                  │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│  第三层：原子原语（纯执行）                                     │
│  控制者：框架执行层                                             │
│                                                               │
│  exec(command="grep -rn deprecated src/")                    │
│    → 权限检查 → 路由到沙箱 → 执行 → 审计 → 返回结果            │
│                                                               │
│  read(source="file:///workspace/src/main.py")                │
│    → 权限检查 → 路由到沙箱文件系统 → 读取 → 审计 → 返回内容     │
│                                                               │
│  这里没有 think，纯执行。                                      │
│  所有原语经过统一的管线：                                       │
│    权限检查 → 多租户隔离 → 安全策略合并 → 执行 → 审计 → 可观测  │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### 27.3 与操作系统的类比

三层结构和操作系统里进程-线程-函数调用的关系完全对应：

```
操作系统：
  进程（有自己的调度循环）→ 有调度器控制
    └─ 线程（有自己的执行流程）→ 有线程库控制
       └─ 函数调用（纯执行）→ CPU 执行

GNEX：
  大 Agent Loop（LLM 决策走哪条路）→ 框架控制
    └─ 复合操作（脚本固定骨架，内层 LLM 决策细节）→ 脚本控制
       └─ 原子原语（纯执行）→ 框架执行层
```

每一层的职责分离：
- **外层**决定"要不要做这件事"（LLM 的语义决策）
- **中层**保证"做这件事的流程骨架不变"（代码的控制流确定性）
- **内层**执行"具体的动作"（原语的原子执行）

### 27.4 为什么这样设计

| 问题 | 解法 | 所在层 |
|------|------|--------|
| LLM 的决策必须依赖上下文 | 每一轮 think-act 都带完整上下文 | 第一层 |
| 复杂操作的流程不能靠 LLM 组装（5% 错误率不可接受） | 用代码脚本固定流程骨架 | 第二层 |
| 执行必须有安全隔离和审计 | 所有原语经过统一管线 | 第三层 |
| 参数临时决定不能影响流程稳定性 | 参数是数据流，脚本是控制流，两者独立 | 第二层 |
| 简单操作不需要额外开销 | LLM 直接输出 GNEX 原语，不查表 | 第一层 → 第三层（跳过第二层） |
