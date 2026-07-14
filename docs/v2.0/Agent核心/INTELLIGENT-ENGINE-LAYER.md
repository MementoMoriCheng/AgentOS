# GNEX 智能引擎层设计文档

> **版本**：v1.3（2026-06-29）  
> **负责人域**：智能引擎层 = **④ 运行时** + **`gnex-agent-sdk` ReAct 内核**  
> **不在本文范围**：② 接入（`d2-access`）· ③ 编排（`d3-orchestration`）· ⑤ 能力注册（`d5-registry`）  
> **评审文档**：[INTELLIGENT-ENGINE-LAYER-REVIEW.md](./INTELLIGENT-ENGINE-LAYER-REVIEW.md)（架构评审 / 签字用）  
> **产品架构 SSOT**：~~[GNexCore架构设计_2.1.html](../GNexCore架构设计_2.1.html)~~（⚠️ 外部 HTML 已不在仓库，相关内容已内化到 [ARCHITECTURE.md](./ARCHITECTURE.md)）
> **工程架构 SSOT**：[LAYER-ARCHITECTURE.md](./LAYER-ARCHITECTURE.md) · [RUNTIME-LAYER.md](./RUNTIME-LAYER.md) · [AGENTOS-SPLIT.md](./AGENTOS-SPLIT.md)  
> **外部 Port 索引**：[INTELLIGENT-ENGINE-INTERFACES.md](./INTELLIGENT-ENGINE-INTERFACES.md) · 方法细节：[RUNTIME-INTERFACE-REFERENCE.md](./RUNTIME-INTERFACE-REFERENCE.md)

**术语**：正文称 **接口**（`gnex-contracts` 中的 Java `interface`）。类名保留 `*Port` 后缀（如 `CoordinatorRuntimePort`）；**接口 = Port**（六边形架构语境下的跨层边界）。

---

## 1. 层定位

### 1.1 一句话定义

**智能引擎层（本文）**是 GNEX Agent 的 **执行内核**：在已选定的 Agent、工具集与 Prompt 就绪后，驱动 **ReAct 循环**（think → act → observe）、上下文压缩、断点续跑、Worker 同步执行与 steering/follow-up 并发语义——**不负责**意图路由、Workflow/Team 编排、Agent/Skill 注册或 HTTP/SSE 暴露。

### 1.2 与《GNexCore架构设计 2.1》对齐

2.1 **产品层 ④ 智能引擎层**包含五块能力；本文 **只 Owner 其中与「执行面」直接相关的子集**：

| 2.1 模块 | GNEX 映射 | 本文 Owner |
|----------|-----------|:----------:|
| **推理引擎** | `ReActLoop` / `ReActTurnLoop` / `ReActLlmInvoker` | ✅ |
| **记忆与上下文** | `ContextCompactor`、`ReActCheckpointService`、Memory Hooks | ✅ |
| **任务执行（动作派发）** | `ReActToolActPhase` → ⑦ Sandbox 接口 | ✅（派发侧） |
| **意图识别** | `Orchestrator` / `AgentRouter` | ❌ → ③ |
| **任务编排** | Workflow / AgentFlow / Team / Room | ❌ → ③ |

2.1 **Agent 引擎**三职责（编排 · 执行 · 协作）中，本文只覆盖 **执行**（ReAct 循环 + 同步 Worker 路径）；**编排**与 **Team / 消息总线协作拓扑** 归 ③。

### 1.3 在九层架构中的位置

```
                    ┌─────────────────────────────────────┐
                    │  ① Web（d1-web）                     │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │  ② 接入（d2-access）      ◄── 不在本文 │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │  ③ 编排（d3-orchestration）◄── 不在本文 │
                    │  Orchestrator · Workflow · Team      │
                    └──────────────────┬──────────────────┘
                                       │ AgentRuntimePort /
                                       │ CoordinatorRuntimePort
┌──────────────────────────────────────▼──────────────────────────────────────┐
│  ★ 智能引擎层（本文）④ 运行时 + gnex-agent-sdk                              │
│  AgentRuntime · ReActLoop · PhasedAgentLoop · MessageQueue · Checkpoint    │
└──────────────┬───────────────────────────────┬──────────────────────────────┘
               │ 消费接口                      │ 消费接口
   ┌───────────▼──────────┐         ┌───────────▼──────────┐
   │  ⑤ 能力注册 d5        │         │  ⑦ Sandbox · ⑧ Bus   │
   │  ◄── 不在本文         │         │  ⑨ 数据 · ⑥ 治理旁路  │
   └──────────────────────┘         └──────────────────────┘
```

### 1.4 边界铁律

| 规则 | 说明 |
|------|------|
| **无 Controller** | 运行时无 REST；HTTP 在 ② |
| **无编排逻辑** | 不实现 Orchestrator、WorkflowEngine、Team 路由；只 **被 ③ 调用** |
| **只暴露 Runtime 接口** | `CoordinatorRuntimePort`、`AgentRuntimePort`、`AgentSyncDelegationPort` 等 |
| **不拥有注册** | Agent/Skill/Tool/LLM 经 ⑤ 接口 **注入**（`ToolCallback[]`、`ChatModel`） |
| **工具必过 Sandbox** | ACT 阶段经 ⑦ `InspectorChain`，运行时无后门 |
| **无 Mapper** | 持久化经 ⑨ Repository / checkpoint 接口 |

### 1.5 范围对照表

| 概念 | 模块 | 本文 |
|------|------|:----:|
| 接入 / 协议 | `d2-access` | ❌ |
| 意图 / 编排 / 协作拓扑 | `d3-orchestration` | ❌ |
| **ReAct 执行内核** | `d4-runtime` + `gnex-agent-sdk` | ✅ |
| 能力注册 | `d5-registry` | ❌ |

---

## 2. 设计目标

| 目标 | 验收 |
|------|------|
| **纯执行** | 给定 `(systemPrompt, userInput, tools, model)` 可独立完成 ReAct 至结束或 checkpoint |
| **可恢复** | `react_checkpoint` true resume；steering/follow-up 队列语义正确 |
| **可替换** | ③⑤⑦⑧⑨ 均通过 interface 契约；`d4` / SDK 无编排/注册实现 import |
| **与 2.1 执行循环一致** | 大 Agent Loop = think→act→observe；校验循环通过 SessionLoop 高优消息由编排层消费，不引入独立调度 |
| **状态外化** | 热 messages/checkpoint 写 ⑨；进程可丢弃重建 |
| **Steering** | turn 边界 `drainSteering`；与 ② 注入的 `MessageQueue` 契约稳定 |

---

## 3. 总体架构

### 3.1 层内组件图

```mermaid
flowchart TB
    subgraph up["上游（非 Owner）"]
        D3["③ Orchestrator / Workflow / Team"]
        D5["⑤ AgentLoader · LLM · Tool 注册"]
    end

    subgraph rt["★ ④ 运行时 + agent-sdk"]
        AR[AgentRuntime]
        PAL[PhasedAgentLoop]
        RL[ReActLoop]
        RTL[ReActTurnLoop]
        ASE[AgentSyncExecutor]
        MQ[MessageQueue]
        CP[ReActCheckpointService]
        CC[ContextCompactor]
        HOOKS[Pre/Post Reasoning Hooks]
        SBX[InspectorChain 控制面门禁]
    end

    subgraph down["下游（非 Owner）"]
        SAND[⑦ Sandbox 执行/调度器]
        DATA[⑨ checkpoint / memory / run_event]
        GOV[⑥ Budget / Audit 旁路]
    end

    D3 -->|CoordinatorRuntimePort| AR
    D3 -->|AgentRuntimePort.delegateToWorker| AR
    AR --> PAL --> RL --> RTL
    ASE --> RL
    RTL --> HOOKS
    RTL -->|LlmConfigPort| D5
    RTL -->|ToolCallback[]| D5
    RTL --> SBX
    SBX -->|SandboxPort| SAND
    RL --> CP --> DATA
    RL --> MQ
    RTL --> GOV
```

> **更正说明（v1.3→v1.4）**：原 mermaid 图将 `InspectorChain` 放在 `⑦ Sandbox` 子图，与实际代码不符——`InspectorChain` 在 `libs/gnex-agent-sdk/src/main/java/com/gnex/agent/boundary/`，是 ④ 运行时 SDK 的控制面门禁。⑦ Sandbox 仅承担"调度器+沙箱内"两道门禁。详见 [AGENT-SERVICE-DESIGN.md §8.4](./AGENT-SERVICE-DESIGN.md)。

### 3.2 2.1 大 Agent Loop → 运行时类映射

> pre-2.0 视角（PREP 经 `MessageQueue.drainSteering` 直注入）。2.0 SessionLoop 驱动路径见 [RUNTIME-LAYER.md §5.3](./RUNTIME-LAYER.md)。

| 2.1 步骤 | 运行时组件 |
|----------|-----------|
| **think** | `ReActTurnPreamble` → `preReasoningHook` → `ReActLlmInvoker` |
| **act** | `ReActToolActPhase` → `ReActToolDispatcher` → ⑦ |
| **observe** | Tool 结果 → `messages`；`postTurnHook` |
| **循环控制** | `ReActCompletionGate`；`DEFAULT_MAX_TURNS=20` |
| **Steering 注入** | `MessageQueue.drainSteering` → 拼入 UserMessage |
| **断点** | `ReActCheckpointService.saveProgress` |

### 3.3 2.1 三层执行结构（运行时视角）

| 层级 | 运行时职责 | 类 |
|------|-----------|-----|
| **① 大 Agent Loop** | 完整 ReAct | `ReActLoop` / `PhasedAgentLoop` |
| **② 复合操作 / Worker** | 子 Agent 同步 ReAct | `AgentSyncExecutor` |
| **③ 原子工具** | 单次 tool call | `ReActToolActPhase` → ⑦ |

编排层决定 **何时进入 ②**（Task 委派、Team 路由）；运行时只提供 **`delegateToWorker` / `execute` API**。

### 3.4 物理模块

| artifact | 内容 |
|----------|------|
| `libs/gnex-agent-sdk` | ReAct 内核：`ReActLoop`、`AgentRuntime`、`MessageQueue`、Hooks、Checkpoint |
| `services/gnex-agent-service/runtime/` | glue：`AgentSyncExecutor` 装配、UiNotifier 等（逐步下沉 SDK） |
| `libs/gnex-contracts/runtime/` | 接口 / DTO Owner 共建 |

---

## 4. 详细设计

### 4.1 门面 API（③ 唯一入口）

```java
// 协调器路径（③ Orchestrator 调用）
ReActResult runCoordinatorReAct(String systemPrompt, String userInput);
ReActResult resumeCoordinatorReAct(ReActCheckpoint checkpoint);

// 最小委派面（③ Task / ⑧ Bus）
String delegateToWorker(String agentName, String taskDescription);

// Worker / 调度直调
ReActResult execute(
    String systemPrompt, String userInput,
    ToolCallback[] tools, int maxTurns, String modelName,
    Supplier<String> steeringSupplier
);
ReActResult resumeExecute(ReActCheckpoint checkpoint, ToolCallback[] tools, Supplier<String> steeringSupplier);
```

**③ 调用前契约**（由编排层装配，运行时消费 ThreadLocal）：

| 字段 | 用途 |
|------|------|
| `sessionId` / `runId` | checkpoint、steering 键 |
| `projectId` | 预算、隔离 |
| `agentName` | 沙箱 profile |
| `depth` / `maxDepth` | 委派防嵌套 |

### 4.2 循环引擎分层

```
PhasedAgentLoop          # 复杂任务 PLAN→EXECUTE→VERIFY；简单直通 ReActLoop
  └─ ReActLoop           # 预算/压缩初始化；FollowUp 外环
       └─ ReActTurnLoop  # 单轮 think→act→observe
            ├─ ReActTurnPreamble    # steering、cancel、限流、熔断
            ├─ ReActLlmInvoker      # 流式 LLM + Token 统计
            ├─ ReActToolActPhase    # 批量 tool call
            └─ ReActCompletionGate  # 无 tool call 时终局判定
```

### 4.3 单轮时序

```
turn_start
  → drainSteering()
  → checkPreLlmGuards()       // cancel / LlmRateLimiter / CircuitBreaker
  → preReasoningHook          // MemoryRecall, ContextTrim, ContextPack
  → ReActLlmInvoker           // ⑤ ChatModel（接口注入）
  → postReasoningHook         // TurnRecorder, AutoMemory
  → [tool_calls?]
       ├ 否 → ReActCompletionGate
       └ 是 → ReActToolActPhase
                → ToolHookPort
                → RiskAwareToolCallback → InspectorChain (⑦)
  → postTurnHook + checkpoint.saveProgress()
turn_end
```

### 4.4 三条执行路径（运行时视角）

| 路径 | 触发方 | 运行时入口 | steering |
|------|--------|-----------|:--------:|
| **A — Coordinator** | ③ Orchestrator | `runCoordinatorReAct` | ✓ |
| **B — Worker** | ③ TaskTool / `delegateToWorker` | `AgentSyncExecutor` → `execute` | ✓ |
| **C — 后台 Job** | ③ AgentScheduler | `SessionLoopPort.fireInbound` | ✓ |

路径 A/B/C 的 **选 Agent、组 Prompt、挂 Workflow** 均在 ③；运行时只执行已准备好的 ReAct。

### 4.5 并发与会话入队

`SessionLoop` + `PriorityInboundQueue`（运行时 Owner）；全局/会话并发仍经 `ChatConcurrencyPort`：

| 机制 | 语义 |
|------|------|
| `tryAcquireGlobal` | 默认 max 8 并发 Chat |
| `tryAcquireSession` | 同 session 串行 |
| **steering** | 高优 `InboundEvent` 入队 |
| **follow-up** | 低优 `InboundEvent`；SessionLoop 续跑 |

② 经 `SessionLoopPort` / `ChatConcurrencyPort` 触发；③ 不直接改 SessionLoop 内部结构。

### 4.6 会话调度（SessionLoop）

**定稿模型**（无双循环）：

```text
SessionLoop
  ├─ PriorityInboundQueue（steering / chat / follow-up / bus）
  └─ runOneTurn() → ReActTurnLoop（单轮 PREP→think→act→observe）
```

SSOT：[SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md)。遗留 `FollowUpContinuationLoop` / MessageQueue 双 Lane 待删除。

### 4.7 Harness 与上下文

| 组件 | 职责 |
|------|------|
| `HarnessRuntime` | 环境契约、过程技能、动作实现、轨迹调节 |
| `ContextCompactor` / `TurnSnipEngine` | 接近 context window 时裁剪 |
| `ReActCheckpointService` | `react_checkpoint.messages_json` |
| Memory Hooks | 读 ⑨ 记忆；写回 L0–L4（存储 Owner ⑨） |

### 4.8 gnex-agent-sdk 边界

| 放 SDK ✅ | 不放 SDK ❌ |
|-----------|-------------|
| `ReActLoop`, `ReActTurnLoop`, `PhasedAgentLoop` | `Orchestrator`, `WorkflowEngine`, `AgentTeamService` |
| `AgentRuntime`, `MessageQueue`, Checkpoint | ⑤ 注册实现、Controller、Mapper |
| Hook 接口 + 默认实现 | ③ 路由、⑤ `AgentRegistryService` |
| `AgentSyncExecutor`（目标迁入 SDK） | SSE 桥接实现 |

---

## 5. 对外接口（运行时 Owner）

| 接口 | 职责 |
|------|------|
| `CoordinatorRuntimePort` | ③ 调协调器 ReAct |
| `AgentRuntimePort` | 最小 `delegateToWorker` |
| `AgentSyncDelegationPort` | Worker 同步委派 |
| `ChatConcurrencyPort` | MQ 全局/会话锁 |
| `ChatSessionPort` / `SessionFollowUpPort` | 会话模式、follow-up |
| `ReActCheckpointQueryPort` | 断点查询 |
| `ProviderTracePort` | LLM 协议 trace |
| `AgentBudgetPort` | turn 前预算（消费 ⑥ 策略） |
| `ChatRunContextPort` | ThreadLocal 上下文 |
| `AgentToolBootstrapPort` | 工具装配（facade 到 ⑤，接口归 runtime 消费方） |
| `QuestionAnswerPort` / `DelegationControlPort` | AskUser / 取消委派 |

完整清单见 [RUNTIME-LAYER.md §5.2](./RUNTIME-LAYER.md)。

---

## 6. 上游 / 下游依赖

> 完整依赖矩阵（含通信模式 P1/P2/P4、2.0 调用路径、OTel）见 [RUNTIME-LAYER.md §7-8](./RUNTIME-LAYER.md)。本节为设计摘要。

运行时 **被调用**（上游）：③ Orchestrator / Workflow / Team / Scheduler · ⑧ Bus · ② 控制（steering/cancel）
运行时 **消费**（上游接口）：⑤ LlmConfigPort / AgentRegistryPort / AgentToolBootstrapPort / ToolHookPort
运行时 **下游**：⑦ Sandbox（InspectorChain / ToolExecutionGateway）· ⑨ 持久化 · ⑥ 治理旁路 · ② SSE 流式事件

---

## 7. 主调用链（仅运行时段）

```
[③] Orchestrator / Scheduler / TaskTool
      │  已完成：选 Agent、组 Prompt、装配 ToolCallback[]
      ▼
[④] AgentRuntime.runCoordinatorReAct / execute / delegateToWorker
      ▼
    PhasedAgentLoop? → ReActLoop
      loop turn:
        LLM ← [⑤] ChatModel
        Tool ← [⑤] callbacks → [⑦] InspectorChain
        checkpoint → [⑨]
        events → RunEventPublisher → [②] SSE
      ▼
    ReActResult → 返回 [③] 汇总
```

---

## 8. 目录结构

```text
libs/gnex-agent-sdk/src/main/java/com/gnex/agent/
├── runtime/          # ReActLoop, AgentRuntime, MessageQueue, Checkpoint, …
├── memory/           # Memory hooks 消费侧（持久化 ⑨）
├── boundary/         # RiskAwareToolCallback（调用 ⑦ 接口）
└── config/           # AgentRuntimeConfiguration

services/gnex-agent-service/.../runtime/
├── AgentSyncExecutor.java      # glue，目标下沉 SDK
├── AgentRuntimeUiNotifier.java
└── …

# 以下非本文 Owner：
#   orchestration/  → ③
#   adapter/        → ③
#   platform/skill/ → ⑤
```

---

## 9. 产出与事件

| 产出 | 存储 | 说明 |
|------|------|------|
| `ReActResult` | 返回 ③ | `{ text, totalTokenUsage }` |
| `ReActCheckpoint` | ⑨ | true resume |
| `agent_run_event` | ⑨ | REACT_START / TOOL_CALL / COMPRESS / … |
| SSE 事件 | → ② | TEXT_CHUNK, TOOL_CALL_*, RISK_CONFIRMATION, … |

---

## 10. 非功能需求

| 维度 | 要求 |
|------|------|
| 线程 | Virtual Thread 承载；`AgentExecutionContext` ThreadLocal |
| 上限 | 20 turns；100 tool calls |
| LLM | `LlmRateLimiter` + `LlmCircuitBreaker`（④ 唯一副本） |
| 上下文 | `ContextCompactor` 在 window 阈值触发 |
| Steering | turn 边界轮询；2.1 目标 &lt;5ms 送达 |
| 测试 | 单测不依赖 ③ Orchestrator 真实例；Mock 接口即可 |

---

## 11. 演进与 Backlog

| 项 | P | Owner |
|----|---|-------|
| SessionLoop 统一 steering/follow-up | P1 | ④ |
| `AgentSyncExecutor` 完全迁入 SDK | P1 | ④ |
| d4 独立 jar + Enforcer（零 ③⑤ import） | P1 | ④ |
| Provider trace / checkpoint 接口巩固 | P2 | ④ |
| 72h 长任务：checkpoint 分片 + 不占 session 锁 | P3 | ④ + ③ 协同时序 |

AgentOS Phase 4：`gnex-agent-sdk` 抽离完成度以 **ReAct 单测 + ③ Mock 集成** 验收。

---

## 12. 测试策略

| 层级 | 示例 |
|------|------|
| **Turn 内核单测** | `ReActTurnLoop` guards、completion gate |
| **MQ 双 Lane** | `MessageQueueDualLaneTest` |
| **边界** | checkpoint round-trip、steering 注入顺序 |
| **集成** | Mock ③ 调用方 + 真 ReActLoop |
| **非本层 E2E** | 编排 E2E 由 ③ 维护；④ 提供模块单测即可 |

---

## 13. 相关文档

| 文档 | 用途 |
|------|------|
| [INTELLIGENT-ENGINE-INTERFACES.md](./INTELLIGENT-ENGINE-INTERFACES.md) | ④ 外部 Port 索引（`gnex-contracts` SSOT） |
| [RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md) | **跨层契约** RC-01–RC-11 |
| [INTELLIGENT-ENGINE-LAYER-REVIEW.md](./INTELLIGENT-ENGINE-LAYER-REVIEW.md) | **架构评审** |
| [RUNTIME-LAYER.md](./RUNTIME-LAYER.md) | 类级职责 SSOT · **§9 与 2.1 差距矩阵** |
| [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) | EventLoop 演进 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 大 Agent Loop / 执行循环（替代已移除的外部 HTML） |
| [LAYER-ARCHITECTURE.md](./LAYER-ARCHITECTURE.md) | 九层边界 |
| [AGENTOS-SPLIT.md](./AGENTOS-SPLIT.md) | SDK 抽离阶段 |

---

## 附录：术语

| 术语 | 含义 |
|------|------|
| **智能引擎层（本文）** | 仅 ④ + `gnex-agent-sdk` |
| **编排** | ③：Orchestrator / Workflow / Team |
| **大 Agent Loop** | 2.1 = GNEX `ReActLoop` |
| **Worker** | `AgentSyncExecutor` 同步子 ReAct |

## 附录：③ / ⑤ 交界（只读）

运行时 **不实现** 下列接口，但依赖其 DTO：

- **③** 实现 `ChatOrchestrationPort` 等；调用 `CoordinatorRuntimePort`
- **⑤** 实现 `LlmConfigPort`、`AgentRegistryPort`、`ToolHookPort`；运行时只消费
