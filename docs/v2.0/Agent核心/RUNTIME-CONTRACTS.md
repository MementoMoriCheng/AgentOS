# Agent 执行内核跨层接口契约

> **版本**：v2.0（2026-06-30）— 微服务架构升级
> **Owner**：④ 运行时 + `gnex-agent-service`
> **代码 SSOT**：`libs/gnex-contracts/.../runtime/`（Java `interface` 定义处）
> **部署 SSOT**：[AGENTOS-SPLIT.md](./AGENTOS-SPLIT.md) §2 B 档
> **关联**：[RUNTIME-LAYER.md](./RUNTIME-LAYER.md) · [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) · [LAYER-ARCHITECTURE.md](./LAYER-ARCHITECTURE.md)

**术语**：正文优先称 **接口**（即 `gnex-contracts` 里的 Java `interface`）。类名仍带 `Port` 后缀（如 `CoordinatorRuntimePort`），是历史命名；**接口 = Port**，六边形架构里的 Port 指「跨模块边界的那组 interface」。

---

## 0. 微服务边界评估

### 0.1 架构决策：agent-sdk 合入 agent-service

**现状**：`gnex-agent-sdk`（160 类，55 个 Spring Bean）作为共享库，被 `gnex-agent-service` 唯一消费。其他服务（bus-service、sandbox-runtime、platform-service）均不依赖它。

**问题**：
- agent-sdk 内 27 处 import platform-service 具体类，违反"共享库不依赖服务"原则
- `com.gnex.agent.service` 包名在两个模块中同时存在（命名空间冲突）
- 55 个 `@Component`/`@Service` 在"库"中——哲学上错误，它们属于服务的应用上下文

**决策**：将 `gnex-agent-sdk` 合入 `gnex-agent-service`。合入后：
- 消除"共享库→服务"的依赖违规类别（不再有 lib→service 问题）
- 94 处跨边界 import 全部归入 agent-service 内部，统一为"agent-service → platform-service"的服务间调用
- `gnex-contracts` 仍是唯一的跨服务契约机制
- agent-service 内部的包结构按 RUNTIME-LAYER.md §3.2 的五子包（loop/react/session/harness/context）重组

### 0.2 服务依赖图

**当前（94 处跨边界 import）**：

```
                    gnex-contracts (85 Port + DTO)
                    ^     ^       ^        ^
                    |     |       |        |
          agent-sdk |     |    bus-svc    |    sandbox-runtime
          (27处违规  |     |    (独立)      |    (独立)
           import)   |     |               |
                |     |     |               |
                v     v     v               v
         gnex-agent-service  gnex-bus-service  gnex-sandbox-runtime
          (67处违规 import)
                |
                | 违规依赖 pom
                v
         gnex-platform-service
```

**目标（agent-sdk 合入后）**：

```
                    gnex-contracts（扩展 Port + DTO + SessionLoop 类型）
                    ^     ^       ^        ^
                    |     |       |        |
                    |     |    bus-svc    |    sandbox-runtime
                    |     |    (独立)      |    (独立)
                    |     |               |
                    |     v               v
         gnex-agent-service  gnex-bus-service  gnex-sandbox-runtime
         (含原 agent-sdk)       |
                |               |
                | 通过 Port 接口 |
                v               v
         gnex-platform-service  (仅依赖 contracts)
```

### 0.3 依赖方向规则

| # | 规则 | 保障 |
|---|------|------|
| R1 | `gnex-agent-service` 不依赖 `gnex-platform-service` 的具体类，仅通过 `gnex-contracts` Port 接口 | Maven enforcer + import 检查 |
| R2 | `gnex-agent-service` 不直接 import `gnex-platform-persistence` 的 entity/mapper，通过 Port 的 DTO 间接访问 | 代码审查 + enforcer |
| R3 | `gnex-contracts` 不依赖任何服务模块 | pom 无服务 artifact |
| R4 | 依赖方向：agent-service → platform-service（单向，不反向） | pom + import 检查 |
| R5 | `gnex-agent-service` 的 pom 不含 `gnex-platform-service` 和 `gnex-platform-persistence` | pom 检查 |

### 0.4 跨服务调用矩阵

| 调用方 | 目标 | 模式 | 传输 | 延迟级别 |
|--------|------|------|------|----------|
| agent-service | platform-service | 同步 RPC | Port + in-process/Feign | 10-100ms |
| agent-service | bus-service | 异步事件 | MessageBusPort | ~ms |
| agent-service | sandbox-runtime | 异步请求/响应 | SandboxPort via MessageBusPort | 1-30s |
| bus-service | agent-service | 异步 fireInbound | SessionLoopPort（新） | ~ms |
| platform-service | agent-service | 异步事件 | MessageBusPort publish | ~ms |

### 0.5 跨边界 import 全景（94 处 → 合入后统一为 agent-service → platform-service）

| platform-service 包 | agent-sdk 处数 | agent-service 处数 | 合计 | 已有 Port | 需新 Port |
|---------------------|---------------|-------------------|------|----------|----------|
| `com.gnex.skill.service` | 5 | 15 | 20 | ToolHookPort | SkillRegistryPort, AutoSkillCatalogPort, SkillOnDiskCatalogPort |
| `com.gnex.skill.entity/mapper` | 0 | 6 | 6 | — | SkillRegistryPort DTO 覆盖 |
| `com.gnex.skill.hook` | 1 | 0 | 1 | ToolHookPort | HookEvent 迁入 contracts |
| `com.gnex.common.observing` | 4 | 5 | 9 | — | LlmMetricsPort, OtelMirrorPort, OtelContextPort |
| `com.gnex.extension` | 5 | 0 | 5 | — | ExtensionSpiPort + SPI 迁入 contracts |
| `com.gnex.agent.service.*` (ps) | 2 | 4 | 6 | — | ModelConfigPort, McpServerConfigPort |
| `com.gnex.agent.tools.CustomToolRegistry` | 1 | 1 | 2 | — | CustomToolQueryPort |
| `com.gnex.agent.quality` | 1 | 0 | 1 | — | SmokeTestPort |
| `com.gnex.trajectory` | 3 | 0 | 3 | — | TrajectoryPort |
| `com.gnex.project` | 2 | 0 | 2 | ProjectManagementPort | ProjectManagementPort 已存在，需补读方法 |
| `com.gnex.billing` | 2 | 2 | 4 | — | BillingQueryPort |
| `com.gnex.credential` | 0 | 1 | 1 | CredentialManagementPort | CredentialManagementPort 已存在，需补运行时查询方法 |
| `com.gnex.agent.entity/mapper` (platform-persistence) | 1 | 16 | 17 | — | 通过 Registry Port DTO 间接访问 |
| `com.gnex.workflow` (platform-persistence) | 0 | 8 | 8 | — | WorkflowQueryPort |
| **合计** | **27** | **67** | **94** | | **13 个新 Port + 3 个已有 Port 补方法** |

---

## 1. 设计原则

| # | 原则 |
|---|------|
| C1 | **编排调用执行，不嵌入执行**。③ 仅依赖 `gnex-contracts`，禁止 import ④ 实现类。 |
| C2 | **能力注入，非拉取注册**。Agent/Tool/LLM 由 ③ 经 ⑤ 接口装配后，④ 只消费已解析产物。 |
| C3 | **Context 先行**。任何 `run*` / `execute` / `delegate*` 前，`ChatRunContext` 必须绑定当前线程。 |
| C4 | **工具必过 Sandbox**。④ 不得绕过 ⑦ `InspectorChain` 直调 OS/网络。 |
| C5 | **取消可协作**。用户 cancel 经 ②→`SessionLoopPort.fireInbound(CANCEL)`；④ 抛 `OperationCancelledException` 或正常结束并写 status。 |
| C6 | **事件与结果分离**。同步返回 `ReActResult`；流式 UI 经 `RunEventPublisher` / `AgentRuntimeUiPort`，不塞进 Result。 |
| C7 | **Port 接口是唯一的跨服务 import 机制**。禁止 import 其他服务的具体类。 |
| C8 | **跨服务数据只通过 DTO**。禁止直接 import 其他服务的 entity/mapper，Port 方法返回 `record` DTO。 |
| C9 | **服务间调用通过 Port + 适配器**。当前用 P1（in-process），Phase 7+ 切 P2（REST/Feign），消费代码零改动。 |
| C10 | **Feature flag 控制循环策略**。`gnex.event-loop.enabled=false` 回退 1.0 双循环。 |

---

## 2. 服务边界目录

### agent-service（D4，含原 agent-sdk）

**暴露**（实现方）：

| Port | 消费方 | 说明 |
|------|--------|------|
| `CoordinatorRuntimePort` | ③ 编排 | 核心执行（RC-01） |
| `AgentSyncDelegationPort` | ③ 编排 | Worker 同步（RC-03） |
| `ChatRunContextPort` | ② 接入 | 上下文绑定（RC-04） |
| `ChatConcurrencyPort` | ② 接入 | 并发锁（RC-05） |
| `ChatActiveRunPort` | ② 接入 | 活跃 Run 追踪 |
| `RunEventRecorderPort` | 内部 | 事件记录（RC-20） |
| `SessionLoopPort` | ②③⑧ | 2.0 统一调度（RC-22） |

**消费**（调用方）：

| Port | 实现方 | 说明 | RC |
|------|--------|------|----|
| `ModelConfigPort` | platform-service | 模型配置 DB | RC-12 |
| `McpServerConfigPort` | platform-service | MCP 配置 DB | RC-13 |
| `SkillRegistryPort` | platform-service | Skill 注册读写 | RC-14 |
| `CustomToolQueryPort` | platform-service | 自定义工具查询 | RC-15 |
| `ExtensionSpiPort` | platform-service | 扩展 SPI 查找 | RC-16 |
| `AutoSkillCatalogPort` | platform-service | Auto skill prompt | RC-17 |
| `SkillOnDiskCatalogPort` | platform-service | 磁盘 skill 扫描 | RC-18 |
| `ToolHookPort` | platform-service | Hook 生命周期 | RC-19 |
| `LlmMetricsPort` | platform-service | LLM 指标记录 | RC-26 |
| `OtelMirrorPort` | platform-service | OTel span 镜像 | RC-21 |
| `OtelContextPort` | platform-service | OTel 上下文传播 | RC-27 |
| `SmokeTestPort` | platform-service | 质量门禁 SPI | RC-28 |
| `TrajectoryPort` | platform-service | 轨迹服务 | RC-29 |
| `BillingQueryPort` | platform-service | 账单查询 | RC-30 |
| `CredentialQueryPort` | platform-service | 凭证运行时查询 | RC-31 |
| `WorkflowQueryPort` | platform-service | 工作流实例查询 | RC-32 |
| `ProjectManagementPort` | platform-service | 项目约束渲染 | 已存在，补方法 |
| `AgentBudgetPort` | ③ 编排 | 执行门禁 | RC-08 |
| `SandboxPort` | sandbox-runtime | 工具执行 | RC-11 |
| `MessageBusPort` | bus-service | 消息总线 | — |

### platform-service（D5）

**暴露**：所有 registry Port、`ExtensionSpiPort`、`OtelMirrorPort`、`LlmMetricsPort`、`OtelContextPort`、`SmokeTestPort`、`TrajectoryPort`、`BillingQueryPort`、`CredentialQueryPort`、`WorkflowQueryPort`

**消费**：仅 `MessageBusPort`（审计事件发布）

### bus-service（D8）

**暴露**：`MessageBusPort`、`AgentMessageBusPort`

**消费**：`SessionLoopPort`（Phase 2b）

### sandbox-runtime（D7）

**暴露**：`SandboxPort`

**消费**：`MessageBusPort`

---

## 3. 核心执行契约（不变）

### RC-01 `CoordinatorRuntimePort`

**实现方**：④ `AgentRuntime`
**调用方**：③ `Orchestrator`

```java
ReActResult runCoordinatorReAct(String systemPrompt, String userInput);
ReActResult runDirectAnswer(String systemPrompt, String userInput);
ReActResult resumeCoordinatorReAct(ReActCheckpoint checkpoint);
void publishRoutingToUi(AgentRoutingMatch match);
```

| 项 | 约定 |
|----|------|
| **前置** | `ChatRunContext` 已绑定；全局+session 锁已 acquire。 |
| **后置** | 返回 `ReActResult(text, totalTokenUsage)`；checkpoint 状态为 `COMPLETED` 或 `RESUMABLE`。 |
| **失败** | 预算拒绝：turn 前由 RC-08 拦截；cancel：`OperationCancelledException`；LLM/工具失败：ERROR 事件 + 可恢复 checkpoint。 |

### RC-02 `AgentRuntimePort`

```java
String delegateToWorker(String targetAgent, String taskDescription);
```

### RC-03 `AgentSyncDelegationPort`

与 RC-02 语义相同；存在历史双接口，新代码统一视为「同步 Worker ReAct 一次」。

---

## 4. 上下文与并发契约（不变）

### RC-04 `ChatRunContext` / `ChatRunContextPort`

| 字段 | 必填 | 用途 |
|------|:----:|------|
| `runId` | ✓ | checkpoint、事件树、replay |
| `sessionId` | ✓ | MQ steering 键、session 锁 |
| `projectId` | ✓ | 预算、租户隔离 |
| `agentName` | ✓ | 沙箱 profile、预算、轨迹 |
| `sseSessionId` | ✓ | UI 事件路由 |
| `userId` | 推荐 | 审计、行级权限 |
| `depth` / `maxDepth` | 委派时 | 防嵌套 |

| 项 | 约定 |
|----|------|
| **生命周期** | 单次 run：bind → run* → finally unbind；**禁止**跨 Virtual Thread 传递未包装 Context。 |

### RC-05 `ChatConcurrencyPort`

```
tryAcquireGlobal() → tryAcquireSession(sessionId) → prepareForNewTurn(sessionId)
  → [ ③ → ④ run* ]
  → releaseSession(sessionId) → releaseGlobal()   // finally
```

### RC-06 `ChatInFlightControlPort`

> 1.0 接口。SessionLoop 2.0 启用后被 `SessionLoopPort.fireInbound` 替代（见 §8 RC-22）。1.0 路径降级保留。

---

## 5. 状态与结果契约（不变）

### RC-07 `ReActCheckpoint` / `ReActCheckpointQueryPort`

```java
record ReActCheckpoint(
    long id, String runId, Long sessionId, String tenantId,
    int nextTurnIndex, int maxTurns, int totalTokenUsage,
    String effectiveModel, String requestedModel,
    String userInput, String messagesJson, String status
);
```

### `ReActResult`

```java
record ReActResult(String text, int totalTokenUsage);
```

---

## 6. D4 消费的 Registry 契约（2.0 新增）

> 以下 Port 接口解决 agent-service → platform-service 的跨服务依赖。每个 Port 将 platform-service 中的具体类抽象为接口，返回 DTO（record），不暴露 entity/mapper。

### RC-12 `ModelConfigPort`

**实现方**：platform-service | **消费方**：`LLMConfigManager`

```java
public interface ModelConfigPort {
    void forEachModelConfig(Consumer<ModelConfigRecord> consumer);
    void registerModel(String modelName, int contextWindow, String provider, @Nullable String tenantId);
}

public record ModelConfigRecord(
    String modelName, int contextWindow, String provider, @Nullable String tenantId
) {}
```

### RC-13 `McpServerConfigPort`

**实现方**：platform-service | **消费方**：`ConfigAuditor`、`AgentToolBootstrap`、`AgentMcpConnector`、`ListMcpToolsTool`、`McpToolRegistry`

```java
public interface McpServerConfigPort {
    List<McpConfigRecord> listAllConfigs();
    McpConfigRecord findByName(String name);
}

public record McpConfigRecord(
    String name, String url, @Nullable String credentialType,
    @Nullable String transportType, boolean enabled
) {}
```

### RC-14 `SkillRegistryPort`

**实现方**：platform-service | **消费方**：`ConfigAuditor`、`AgentToolBootstrap`、`SkillLoader`、`TeamSkillInstaller`、`AgentInstallService`、`AgentUninstallService`、`DevMapService`、`ListSkillsTool`、`SkillListUserFormatter`

```java
public interface SkillRegistryPort {
    List<SkillRecord> listAllSkills(@Nullable String domain);
    SkillRecord findSkillByName(String name);
    String findSummaryByName(String name);
    SkillRecord addSkill(SkillRecord skill);
    void removeSkillByName(String name);
}

public record SkillRecord(
    String name, String source, String definitionPath,
    @Nullable String ownerAgent, @Nullable String domain,
    @Nullable String content
) {}
```

> **命名说明**：与已有 `SkillImportPort`（导入外部 skill 文件）不同。`SkillRegistryPort` 管理 GNEX 内部 skill 注册表的读写。

### RC-15 `CustomToolQueryPort`

**实现方**：platform-service | **消费方**：`ConfigAuditor`、`CustomToolManagementPortAdapter`

```java
public interface CustomToolQueryPort {
    List<CustomToolRecords.ToolInfo> listToolInfos();
    List<CustomToolRecords.CustomToolDef> listCustomToolDefs();
}
```

### RC-16 `ExtensionSpiPort`

**实现方**：platform-service | **消费方**：`RiskInspector`、`RiskAwareToolCallback`

```java
public interface ExtensionSpiPort {
    RiskClassifier getRiskClassifier();
    ApprovalHandler getApprovalHandler();
    @Nullable NotificationHandler getNotificationHandler();
}
```

> `RiskClassifier`、`ApprovalHandler`、`NotificationHandler` SPI 接口从 `com.gnex.extension.spi` 迁移到 `gnex-contracts/runtime/`。

### RC-17 `AutoSkillCatalogPort`

**实现方**：platform-service | **消费方**：`OrchestratorPromptLoader`

```java
public interface AutoSkillCatalogPort {
    String buildAutoSkillSection(@Nullable String agentName);
}
```

### RC-18 `SkillOnDiskCatalogPort`

**实现方**：platform-service | **消费方**：`TeamSkillInstaller`、`ListSkillsTool`

```java
public interface SkillOnDiskCatalogPort {
    List<SkillRecord> scan();
}
```

### RC-19 `ToolHookPort`（已存在，补 HookEvent）

**实现方**：platform-service `HookExecutor` | **消费方**：`AgentRuntime`、`ReActLoop`、`ReActToolDispatcher`、`AgentScheduler`、`AgentSyncExecutor`、`AsyncAgentExecutor`

已存在于 `gnex-contracts/registry/ToolHookPort`。需将 `HookEvent` 枚举从 `com.gnex.skill.hook` 迁入 `gnex-contracts/registry/`，作为 `ToolHookPort` 的配套 DTO。

---

## 7. 诊断与可观测契约（2.0 新增）

### RC-20 `RunEventRecorderPort`

**实现方**：agent-service `AgentRunEventService` | **消费方**：agent-service 内 11 个类

```java
public interface RunEventRecorderPort {
    Long recordModelCall(String runId, Long sessionId, String modelCallId,
                         String modelName, String inputPreview, String outputPreview,
                         int tokenCount, long durationMs, @Nullable Long parentEventId);
    Long recordToolCall(String runId, Long sessionId, String toolCallId,
                        String toolName, String arguments, String result,
                        long durationMs, @Nullable Long parentEventId);
    Long recordPhase(String runId, Long sessionId, String phaseName,
                     String detail, @Nullable Long parentEventId);
    Long recordCompress(String runId, Long sessionId,
                        int beforeTokens, int afterTokens, long durationMs,
                        @Nullable Long parentEventId);
    Long recordError(String runId, Long sessionId, String errorMessage,
                     @Nullable Long parentEventId);
    Long recordAnomaly(String runId, Long sessionId, String warning,
                       @Nullable Long parentEventId);
    Long recordDelegation(String runId, Long sessionId, String agentName,
                          String taskDescription, String delegationId,
                          @Nullable Long parentEventId);
    void clearRunSequence(String runId);
}
```

### RC-21 `OtelMirrorPort`

**实现方**：platform-service | **消费方**：`AgentRunEventService`、`ExecutionLogService`

```java
public interface OtelMirrorPort {
    void mirrorEvent(String eventType, String runId, Long sessionId,
                     String eventName, @Nullable String delegationId,
                     @Nullable String inputPreview, @Nullable String outputPreview,
                     int tokenCount, long durationMs);
    void clearRun(String runId);
}
```

### RC-26 `LlmMetricsPort`

**实现方**：platform-service | **消费方**：`ReActLlmInvoker`、`ReActLoop`、`ReActModelFallback`

```java
public interface LlmMetricsPort {
    void recordLlmCall(String modelName, int promptTokens, int completionTokens,
                       long durationMs, @Nullable String provider);
}
```

### RC-27 `OtelContextPort`

**实现方**：platform-service | **消费方**：`AgentScheduler`、`AsyncAgentExecutor`、`ChatAgentStreamRunner`

```java
public interface OtelContextPort {
    Runnable wrapWithContext(Runnable task);
    @Nullable String currentTraceId();
}
```

> 包装 OTel 上下文传播逻辑，使 agent-service 不直接依赖 `OtelContextPropagation` 和 `AgentMetrics`。

---

## 8. SessionLoop 契约（2.0 新增）

### RC-22 `SessionLoopPort`

**实现方**：agent-service `SessionLoopRegistry`（2.0）或 `LegacySessionLoopPortAdapter`（1.0 降级）
**消费方**：② `ChatControlController`、③ `Orchestrator`、⑧ bus-service（Phase 2b）

```java
public interface SessionLoopPort {
    void fireInbound(Long sessionId, InboundKind kind, String payload);
    void wakeUp(Long sessionId);
    boolean isBusy(Long sessionId);
    void attachSse(Long sessionId, String sseSessionId);
    void detachSse(Long sessionId);
    ChannelStatus getChannelStatus(Long sessionId);
}
```

| 方法 | 替代的 1.0 方法 |
|------|----------------|
| `fireInbound(sid, CANCEL, ...)` | `ChatInFlightControlPort.cancelBySession` |
| `fireInbound(sid, STEERING, ...)` | `ChatInFlightControlPort.queueSteering` |
| `fireInbound(sid, USER_TURN, ...)` | ② 直接调 ③ run |
| `fireInbound(sid, FOLLOW_UP, ...)` | `ChatInFlightControlPort.queueFollowUp` |
| `fireInbound(sid, BUS_TASK, ...)` | `AsyncAgentExecutor.submitJob` |
| `wakeUp(sid)` | 无（1.0 无此概念） |
| `isBusy(sid)` | `ChatConcurrencyPort.tryAcquireSession` |
| `attachSse/detachSse` | `ChatActiveRunPort` 间接管理 |

**Feature Flag**：`gnex.event-loop.enabled=false` → `LegacySessionLoopPortAdapter`；`true` → `SessionLoopRegistry`

### RC-23 `InboundKind` + `InboundEvent`

```java
public enum InboundKind {
    CANCEL(0), STEERING(1), USER_TURN(2), FOLLOW_UP(3), BUS_TASK(4);
    public final int priority;
    InboundKind(int priority) { this.priority = priority; }
}

public record InboundEvent(
    InboundKind kind, String payload, Instant enqueuedAt, Map<String, String> metadata
) {}
```

### RC-24 `TurnResult` + `LoopControlDecision`

```java
public enum TurnResult { REACT_DONE, TOOL_CALL_PENDING, BUDGET_EXHAUSTED, ERROR }
public enum LoopControlDecision { RUN_ONE_TURN, COMPLETE, CANCELLED, YIELD_SLICE }
```

| TurnResult | LoopControlDecision | 条件 |
|------------|---------------------|------|
| REACT_DONE | COMPLETE | 队列无 FOLLOW_UP / USER_TURN |
| REACT_DONE | RUN_ONE_TURN | 队列有 FOLLOW_UP / USER_TURN |
| TOOL_CALL_PENDING | RUN_ONE_TURN | 继续 |
| BUDGET_EXHAUSTED | YIELD_SLICE | checkpoint + bus 续跑 |
| ERROR | COMPLETE / RUN_ONE_TURN | 取决于重试次数 |

### RC-25 `ChannelStatus`

```java
public enum ChannelStatus { IDLE, PROCESSING, YIELDING, STALLED, COMPLETED, CANCELLED }
```

---

## 9. 补充 Registry 契约（2.0 新增，覆盖遗漏的跨服务依赖）

### RC-28 `SmokeTestPort`

**实现方**：platform-service | **消费方**：`LiveSmokeTestProvider`

```java
public interface SmokeTestPort {
    boolean runSmokeTest(String agentName, String modelName);
}
```

> `SmokeTestProvider` 接口从 `com.gnex.agent.quality` 迁入 `gnex-contracts/governance/`。

### RC-29 `TrajectoryPort`

**实现方**：platform-service | **消费方**：`HarnessRuntime`、`ProceduralSkillInjector`

```java
public interface TrajectoryPort {
    List<TrajectoryRecord> queryRecentTrajectories(String agentName, int limit);
    List<PatternRecord> extractPatterns(String agentName);
}

public record TrajectoryRecord(String sessionId, String summary, Instant completedAt) {}
public record PatternRecord(String pattern, double confidence, int occurrenceCount) {}
```

### RC-30 `BillingQueryPort`

**实现方**：platform-service | **消费方**：`UsageTracker`、`OperationsMetricsService`

```java
public interface BillingQueryPort {
    List<ModelPricingRecord> listModelPricing();
    BillingOverviewResponse queryOverview(@Nullable String agentName, @Nullable Long projectId);
}

public record ModelPricingRecord(String modelName, double inputPricePerToken, double outputPricePerToken) {}
```

> `UsageTracker` 的写操作（`TokenUsage` 插入）需要额外处理：写操作留在 agent-service 内部（`TokenUsage` 表归 agent-service 管），读操作（`ModelPricing` 查询）走此 Port。这意味着 `TokenUsage` + `TokenUsageMapper` 应迁入 `gnex-agent-persistence`，从 `gnex-platform-persistence` 移出。

### RC-31 `CredentialQueryPort`

**实现方**：platform-service | **消费方**：`McpToolRegistry`

```java
public interface CredentialQueryPort {
    @Nullable CredentialRecord findCredentialByName(String name);
}

public record CredentialRecord(String name, String type, @Nullable String maskedValue) {}
```

> 已有 `CredentialManagementPort`（CRUD 管理），`CredentialQueryPort` 补运行时查询（MCP 工具连接时需要凭证）。

### RC-32 `WorkflowQueryPort`

**实现方**：platform-service | **消费方**：`PlanExecutor`、`DevMapService`

```java
public interface WorkflowQueryPort {
    @Nullable WorkflowInstanceRecord findInstanceById(Long instanceId);
    List<WorkflowInstanceRecord> listInstancesByStatus(String status);
    void updateInstanceStatus(Long instanceId, String status, @Nullable String result);
    void appendNodeLog(Long instanceId, String nodeName, String status, @Nullable String output);
}

public record WorkflowInstanceRecord(
    Long id, String name, String status, @Nullable String result,
    @Nullable Long projectId, Instant createdAt, Instant updatedAt
) {}
```

> `PlanExecutor` 当前直接写 `WorkflowInstanceMapper` 和 `WorkflowNodeLogMapper`。拆分后写操作必须走 Port。这是少数"agent-service 写 platform-service 的表"的场景，需要明确表归属。

---

## 10. 跨服务通信模式

| 模式 ID | 名称 | 何时用 | 同步/异步 | 传输抽象 |
|---------|------|--------|----------|---------|
| P1 | In-Process Port | 拆分期，dev-assembler 单体 | 同步 | Spring @Component 实现 Port |
| P2 | REST RPC | Phase 7+，服务独立部署 | 同步 | Port + @FeignClient 适配器 |
| P3 | MessageBus Event | 即发即弃、扇出 | 异步 | MessageBusPort.publish |
| P4 | MessageBus Req/Resp | 工具执行、沙箱调用 | 异步 | SandboxPort |
| P5 | fireInbound | Steering/Bus→Session/Cancel | 异步 | SessionLoopPort.fireInbound |

**当前阶段全用 P1**。拆分后切 P2 适配器，消费代码零改动。

### D4 消费 platform-service 完整调用表

| D4 消费方 | Platform 数据 | Port | 当前 P1 | Phase 7+ P2 |
|-----------|-------------|------|---------|-------------|
| LLMConfigManager | 模型配置 | ModelConfigPort | 包装 ModelConfigService | REST `/api/v1/models/config` |
| ConfigAuditor | MCP 配置 | McpServerConfigPort | 包装 McpServerConfigService | REST `/api/v1/mcp/configs` |
| ConfigAuditor | 自定义工具 | CustomToolQueryPort | 包装 CustomToolRegistry | REST `/api/v1/custom-tools` |
| ConfigAuditor | Skill 列表 | SkillRegistryPort | 包装 SkillRegistryService | REST `/api/v1/skills` |
| AgentToolBootstrap | Skill/MCP 定义 | SkillRegistryPort + McpServerConfigPort | 同上 | 同上 |
| OrchestratorPromptLoader | Auto skill 段 | AutoSkillCatalogPort | 包装 AutoSkillCatalog | REST `/api/v1/skills/auto-section` |
| RiskInspector/RiskAwareToolCallback | 风险/审批 SPI | ExtensionSpiPort | 包装 ExtensionRegistry | REST `/api/v1/extensions/spi` |
| ReActLlmInvoker/ReActLoop | LLM 指标 | LlmMetricsPort | 包装 LlmMetrics | REST `/api/v1/llm/metrics` |
| AgentRunEventService/ExecutionLogService | OTel 镜像 | OtelMirrorPort | 包装 AgentRunOtelBridge | 直连 OTel |
| AgentScheduler/AsyncAgentExecutor | OTel 上下文 | OtelContextPort | 包装 OtelContextPropagation | 直连 OTel |
| LiveSmokeTestProvider | 质量门禁 | SmokeTestPort | 包装 SmokeTestProvider | REST `/api/v1/quality/smoke-test` |
| HarnessRuntime/ProceduralSkillInjector | 轨迹 | TrajectoryPort | 包装 TrajectoryService | REST `/api/v1/trajectory` |
| ProjectConstraintRenderer | 项目约束 | ProjectManagementPort | 已存在，补方法 | REST `/api/v1/projects` |
| UsageTracker/OperationsMetricsService | 账单查询 | BillingQueryPort | 包装 BillingService | REST `/api/v1/billing` |
| McpToolRegistry | 凭证查询 | CredentialQueryPort | 包装 CredentialHandler | REST `/api/v1/credentials` |
| PlanExecutor/DevMapService | 工作流实例 | WorkflowQueryPort | 包装 WorkflowInstanceMapper | REST `/api/v1/workflows` |

---

## 11. 预算与治理契约（不变）

### RC-08 `AgentBudgetPort`

| 方法 | 调用点 | 约定 |
|------|--------|------|
| `checkBudget(agent, projectId)` | turn 前 | 非 null = 拒绝原因 |
| `checkoutTokens(...)` | turn 后 | 失败记审计 |

### RC-09 工具与 LLM 注入

| 接口 | 用途 |
|------|------|
| `LlmConfigPort` | 创建 `ChatModel` |
| `AgentRegistryPort` | Agent 定义 |
| `AgentToolBootstrapPort` | `ToolCallback[]` |
| `ToolHookPort` | ACT 前后 Hook |

### RC-10 `RunEventPublisher`

| 项 | 约定 |
|----|------|
| **实现方** | glue → ② SSE |
| **顺序** | `STREAM_ACK` → … → `COMPLETED`/`ERROR`；带 `runId` + monotonic seq |

### RC-11 工具执行（④ → ⑦）

```
ReActToolActPhase → RiskAwareToolCallback → InspectorChain.inspect()
  → DENY: 工具错误回写 messages
  → CRITICAL: RC-10 确认流
  → ALLOW: ToolExecutionGateway 执行
```

---

## 12. 端到端时序（微服务视角）

### 12.1 Chat 主路径（2.0）

```
② acquire RC-05
② bind RC-04 (runId, sessionId, …)
② → ③ ChatOrchestrationPort.processStream(...)
③ 装配 systemPrompt（Registry Ports → platform-service）
③ → RC-01 runCoordinatorReAct(prompt, userInput)
  loop ④:
    RC-08 checkBudget
    SessionLoop poll PriorityInboundQueue
    LLM ← RC-12 ModelConfigPort (P1 → platform-service)
    LLM metrics ← RC-26 LlmMetricsPort (P1 → platform-service)
    tool ← RC-11 SandboxPort (P4 → sandbox-runtime)
    checkpoint ← RC-07
    events ← RC-10 RunEventPublisher
    diagnostics ← RC-20 RunEventRecorderPort
③ 返回 ReActResult
② release RC-05 (finally)
```

### 12.2 Steering/Cancel（2.0）

```
② ChatControlController
  → SessionLoopPort.fireInbound(sessionId, STEERING/CANCEL, payload)
  → agent-service SessionLoopRegistry
    → PriorityInboundQueue 入队 → SessionLoop VT poll → 下 turn 生效
```

### 12.3 Bus 消息（Phase 2b）

```
⑧ MessageBusConsumer → SessionLoopPort.fireInbound(sessionId, BUS_TASK, payload)
  → SessionLoop → ReActTurnEngine.runOneTurn()
  → OutboundDispatcher → MessageBusPort.publish
```

---

## 13. 数据归属与持久层清理

> agent-sdk 合入 agent-service 后，需清理持久层依赖。原则：**谁的服务管谁的表**。

| 表 | 当前归属 | 目标归属 | 理由 |
|----|---------|---------|------|
| `react_checkpoint` | agent-persistence | agent-persistence | agent-service 读写，不迁移 |
| `agent_run_event` | agent-persistence | agent-persistence | agent-service 读写，不迁移 |
| `token_usage` | platform-persistence | **→ agent-persistence** | `UsageTracker`（agent-service）写入，agent-service 独占 |
| `model_pricing` | platform-persistence | platform-persistence | platform-service 管理，agent-service 通过 BillingQueryPort 只读 |
| `agent_registry` | platform-persistence | platform-persistence | platform-service CRUD，agent-service 通过 AgentRegistryPort 访问 |
| `mcp_server_config` | platform-persistence | platform-persistence | platform-service 管理，agent-service 通过 McpServerConfigPort 只读 |
| `workflow_instance` / `workflow_node_log` | platform-persistence | platform-persistence | platform-service 管理，agent-service 通过 WorkflowQueryPort 读写 |
| `tenant_prompt_config` | platform-persistence | platform-persistence | platform-service 管理，agent-service 通过 Port 只读 |
| `agent_credential` | platform-persistence | platform-persistence | platform-service 管理，agent-service 通过 CredentialQueryPort 只读 |

**关键迁移**：`token_usage` 表从 `gnex-platform-persistence` 迁入 `gnex-agent-persistence`，`UsageTracker` 随之不再依赖 platform-persistence。

---

## 14. 版本与演进

| 版本 | 范围 | 变更 |
|------|------|------|
| **v1** | RC-01–RC-11 | 单体架构 |
| **v1.1** | + RunDeadline + RuntimeFailureCode | — |
| **v2.0（当前）** | RC-01–RC-32 | agent-sdk 合入 agent-service；16 个 Port（9 新 + 3 已有补方法 + 4 SessionLoop 类型）；P1/P5 通信模式；数据归属清理 |
| **v2.1** | StatePort 实现；P2 REST/Feign 适配器 | Phase 7+ |
| **v3** | SteeringChannel（WS cancel）；gRPC | Phase 7+ |

---

## 15. 验收检查

| # | 检查 | 优先级 | 方法 |
|---|------|--------|------|
| T1 | ③ 零 `import ...AgentRuntime` | P0 | Enforcer |
| T2 | 无 Context bind 时 RC-01 fast-fail | P0 | 单元测试 |
| T3 | acquire 未 release 无泄漏 | P0 | 压测 |
| T4 | checkpoint round-trip 一致 | P0 | 集成测试 |
| T5 | steering 在 turn N+1 生效 | P0 | 集成测试 |
| T6 | budget 拒绝产生 ERROR 事件 | P1 | Mock RC-08 |
| T7 | CRITICAL 未确认不执行 tool | P1 | E2E |
| **T8** | agent-service 零 `import com.gnex.skill.service.*` / `com.gnex.extension.*` / `com.gnex.common.observing.*` / `com.gnex.trajectory.*` / `com.gnex.project.service.*` / `com.gnex.billing.service.*` / `com.gnex.credential.*` | **P0** | Maven enforcer + grep CI |
| **T9** | agent-service pom 不含 `gnex-platform-service` + `gnex-platform-persistence` | **P0** | pom 检查 |
| **T10** | agent-service 零 `import com.gnex.agent.service.ModelConfigService` 等 platform-service 具体类 | **P0** | grep CI |
| **T11** | agent-service 零 `import` platform-persistence 的 entity/mapper（`AgentRegistry`、`McpServerConfig`、`TokenUsage`、`ModelPricing`、`TenantPromptConfig`、`AgentCredential`、`WorkflowInstance`、`WorkflowNodeLog`、`SkillRegistry`、`SkillRegistryMapper`） | **P1** | grep CI |
| **T12** | SessionLoopPort 1.0 降级 `enabled=false` 正常 | P1 | 集成测试 |
| **T13** | dev-assembler 启动 + Chat API 不退化 | P0 | E2E |
| **T14** | `token_usage` 表迁入 agent-persistence 后，platform-persistence 不再包含 | P1 | pom + migration 检查 |

---

## 16. 相关文档

| 文档 | 内容 |
|------|------|
| [AGENTOS-SPLIT.md](./AGENTOS-SPLIT.md) | AgentOS 拆分 SSOT、部署拓扑 |
| [RUNTIME-LAYER.md](./RUNTIME-LAYER.md) | D4 层 2.0 架构、模块重组 |
| [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) | SessionLoop 架构 SSOT |
| [LAYER-ARCHITECTURE.md](./LAYER-ARCHITECTURE.md) | 九层架构、依赖矩阵 |
| `libs/gnex-contracts/.../runtime/` | 接口源码 |

---

*本文档为跨层行为契约 SSOT v2.0；与 Java 接口签名冲突时，以 contracts 源码为准，并须同步修订本文。*
