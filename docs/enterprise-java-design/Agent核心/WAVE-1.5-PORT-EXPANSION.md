# Wave 1.5 — Port API 扩展 + Violation 收敛

**版本**：v1（2026-07-07）
**分支**：`feature/wave-1.5-port-expansion`（1 commit，待 review）
**前置**：[Wave 1 SessionLoop](./WAVE-1-SESSION-LOOP-DESIGN.md) ✅
**参照**：[SESSION-LOOP-SINGLE-STACK-CUTOVER.md](../../SESSION-LOOP-SINGLE-STACK-CUTOVER.md) §3 Wave 1.5

---

## 概览

Wave 1.5 扩展 4 个 Port API + 迁移 1 个值对象，将 react→harness ArchUnit violations 从 329 降到 178（46% reduction）。

| Phase | 内容 | 实际工作量 | 计划估 | 状态 |
|-------|------|-----------|-------|:----:|
| 1 | RunObservabilityPort 扩展 | 0.3 人周 | 0.3 | ✅ |
| 2 | LlmConfigPort 扩展 | 0.2 人周 | 0.3 | ✅ |
| 3 | AuthProfilePort 扩展 | 0.1 人周 | 0.2 | ✅ |
| 4 | ChatRunContext 扩展 | 0.4 人周 | 0.5 | ✅ |
| 5 | StrictnessLevel 迁 contracts/ | 0.1 人周 | 0.2 | ✅ |
| **合计** | | **1.1 人周** | **1.5** | |

实际比计划估低 27%，主要节省来自 ChatRunContext 只做部分转换（16/22 个文件）。

---

## 1. P1 — RunObservabilityPort 扩展

### 1.1 原始 gap

Port 只有 `mirrorEvent` + `clearRun` 2 个方法。react/ 实际调用 7 个 record 方法。

### 1.2 落地

**contracts/diagnostics/RunObservabilityPort 新增 7 个方法**：
- `recordPhase(runId, sessionId, phaseName, detail, parentEventId) → Long`
- `recordModelCall(runId, sessionId, modelCallId, modelName, inputPreview, outputPreview, tokenCount, durationMs, parentEventId) → Long`
- `recordToolCall(runId, sessionId, toolCallId, toolName, arguments, result, durationMs, parentEventId) → Long`
- `recordCompress(runId, sessionId, beforeTokens, afterTokens, durationMs, parentEventId) → Long`
- `recordError(runId, sessionId, errorMessage, parentEventId) → Long`
- `recordAnomaly(runId, sessionId, warning, parentEventId) → Long`
- `clearRunSequence(runId)`

**AgentRunEventService implements RunObservabilityPort**，所有 record 方法加 `@Override`，新增 `mirrorEvent` + `clearRun` 委托实现。

**AgentRunOtelBridge** 实现新增方法——record 方法内转调 `mirrorEvent`，`clearRunSequence` 委托 `clearRun`。

**11 个文件替换**（10 react/ + 1 context/）：`AgentRunEventService` → `RunObservabilityPort`。

### 1.3 效果

AgentRunEventService violations 从 76 → 0（完全消除）。context/ violations 从 10 → 7。

---

## 2. P2 — LlmConfigPort 扩展

### 2.1 原始 gap

Port 14 方法，缺 `createChatModel` / `getContextWindow` / `getFallbackModels` / `recordAuthProfileSuccess` / `rotateAuthProfile`。

### 2.2 落地

**contracts/registry/LlmConfigPort 新增 5 个方法**：
- `ChatModel createChatModel()` — contracts/ 已有 spring-ai-model 依赖
- `int getContextWindow(String modelName)`
- `List<String> getFallbackModels()`
- `default void recordAuthProfileSuccess()` — no-op default
- `default boolean rotateAuthProfile()` — false default

后两个是 default 方法，LLMConfigManager 已有实现。AuthProfile 相关方法暂时放 LlmConfigPort（等 Wave 2 拆 AuthProfilePort 时再迁移）。

**5 个 react/ 文件替换**：ReActCompletionGate, ReActLlmInvoker, ReActLoop, ReActModelFallback, ReActTurnLoop。

### 2.3 效果

LLMConfigManager violations 从 58 → 0（完全消除）。

---

## 3. P3 — AuthProfilePort 扩展

### 3.1 原始 gap

Port 3 方法（`evictExpired` / `getActiveProfile` / `resolveEnvValue`），缺 `findProfileNameByApiKey` / `recordFailure`。

### 3.2 落地

**contracts/registry/AuthProfilePort 新增 2 个方法**：
- `String findProfileNameByApiKey(String apiKey)`
- `void recordFailure(String profileName)`

**2 个 react/ 文件替换**：ReActLoop, ReActTurnLifecycle。

### 3.3 效果

AuthProfileManager 不在 harness/ 包中（在 runtime/），不影响 ArchUnit react→harness 规则。但改善了架构——react/ 不再依赖 SDK 内部 runtime/ 包。

---

## 4. P4 — ChatRunContext 扩展（部分完成）

### 4.1 设计决策

**ChatRunContext extends ToolExecutionContextView** — 合并两个 ThreadLocal 访问链。`AgentExecutionContext.set()` 已同时绑定 `ToolExecutionContexts`，所以 `ChatRunContext.current()` 通过 `ToolExecutionContexts.current()` 实现类型安全的 upcast。

**static current()** — Java 8+ 接口静态方法，返回 `@Nullable ChatRunContext`。

### 4.2 新增方法

| 方法 | 类型 | 用途 |
|------|------|------|
| `getDepth()` | getter | 委派嵌套深度 |
| `getCurrentJobId()` | getter | Job ID（Port 只有 setter） |
| `getModelCallEventId()` / `setModelCallEventId()` | getter/setter | 决策归因树 |
| `getDelegationCancelToken()` | getter | 子 Agent 取消令牌 |
| `getLastOutputsReportPath()` | getter | 输出报告路径 |
| `hasSingleFileReadCompleted()` | boolean | 单文件审查门控 |
| `tryMarkSseRunningEmitted()` | boolean | SSE 去重 |
| `getCompletionEvidence()` / `setCompletionEvidence()` | getter/setter | 完成证据 |
| `getAssistantMessageId()` | getter | DB 消息 ID |
| + ToolExecutionContextView 12 个方法 | lift | 提升 getter 到 ChatRunContext |

### 4.3 转换分类

| 分类 | 文件数 | 说明 |
|------|:------:|------|
| 可完全转换 | 16 | 只用 ChatRunContext 上的方法 |
| 不可转换 | 6 | 需要 ProviderTraceCollector / TodoSessionTracker / L0TurnDraft / AgentExecutionContext 字段 |
| 已无引用 | 4 | 之前已无 AgentExecutionContext 引用 |

**16 个已转换文件**：MemoryRecallHook, AutoMemoryHook, DecisionRecorder, ProjectConstraintRenderer, TurnRecorder, SteeringSuppliers, ReActSseNotifier, FollowUpContinuationLoop, PhasedAgentLoop, ReActTurnPreamble, ReActLlmInvoker, ReActToolDispatcher, ReActLoop, ContextPackRecorder, ContextCompactor, ToolResultOffloader

**6 个未转换文件**（需 Wave 2 Port 化）：

| 文件 | 阻塞原因 |
|------|---------|
| ReActCompletionGate | `getTodoTracker()` → TodoSessionTracker |
| ReActToolActPhase | `recordL0ToolExecution()` → L0TurnDraft |
| ReActContextHelpers | `execCtxForL0()` 返回 AgentExecutionContext |
| ReActTurnLifecycle | `getProviderTraceCollector()` → ProviderTraceCollector |
| SessionMemoryRecorder | L0TurnDraft 全套方法 |
| ActiveRunRegistry | AgentExecutionContext 作为 record 字段类型 |

### 4.4 效果

AgentExecutionContext violations 从 160 → 85（消除 75，47% reduction）。

---

## 5. P5 — StrictnessLevel 迁 contracts/runtime/

纯枚举，无依赖。git mv + sed 改 import + harness/ 内文件加显式 import。

消除 5 violations。

ConstrainedDecodingLayer 不迁——有 react/ 依赖（ToolCallSchemaValidator 等），不是纯值对象。

---

## 6. ArchUnit Baseline 演化

| 阶段 | react→harness | context→react/harness | 说明 |
|------|:----:|:----:|------|
| Wave 0.5 完 | 371 | 10 | 初始冻结 |
| Wave 1 P4.1 完 | 329 | 10 | RouteDecision 迁出 -42 |
| Wave 1.5 P1 完 | 285 | 7 | AgentRunEventService 消除 -44 |
| Wave 1.5 P2 完 | 258 | 7 | LLMConfigManager 消除 -27 |
| Wave 1.5 P4 完 | 183 | 1 | ChatRunContext 转换 -75 |
| Wave 1.5 P5 完 | **178** | **1** | StrictnessLevel 消除 -5 |

**总降幅**：329 → 178（-46%）

---

## 7. Wave 2 前置工作

基于 P4 实测发现的 6 个未转换类，Wave 2 需要的 Port 化：

1. **ProviderTraceCollectorPort** — 抽 `recordAssistantToolCall` / `recordToolResponse` + `hasToolCalls` / `isComplete` / `getProtocolMessages` / `estimateTokens` / `getProvider` / `getModel`
2. **TodoTrackerPort** — 抽 `canNudgeContinue` / `inProgressSummary` / `nextContinuePrompt`（或简单化为 boolean `hasIncompleteTodos`）
3. **L0JournalPort** — 抽 `setL0TurnDraft` / `getL0TurnDraft` / `clearL0TurnDraft` / `recordL0ToolExecution` / `getL0ToolExecutions`
4. **ActiveRunRegistry 重构** — 把 `AgentExecutionContext` record 字段替换为 `ChatRunContext`

预期收益：85 → 0 AgentExecutionContext violations。

---

## 8. 剩余 178 violations 分布

| harness 类 | violations | 需 Port |
|-----------|:---------:|---------|
| AgentExecutionContext | 85 | ChatRunContext 续 + 3 个新 Port |
| HarnessRuntime | 44 | 新 HarnessRuntimePort |
| LlmCircuitBreaker | 27 | 新 LlmResiliencePort |
| ModelRouter | 25 | 新 ModelRouterPort |
| TokenSaver | 22 | 合并入 LlmConfigPort 或新 Port |
| LlmRateLimiter | 20 | 合并入 LlmResiliencePort |
| RoutingMetrics | 18 | 新 RoutingPort 或合并 |
| TokenJuice + ApplyResult | 34 | 新 TokenJuicePort |
| UsageTracker | 16 | 合并入 RunObservabilityPort |
| DelegationCancelRegistry | 16 | 新 DelegationPort |
| ConstrainedDecodingLayer | 7 | 留 harness/ 或拆 PreValidation record |
| ProviderTraceCollector | 2 | ProviderTraceCollectorPort |

预期 Wave 2 全量 Port 化后：178 → 0。

---

*Wave 1.5 设计稿 v1，2026-07-07，基于 feature/wave-1.5-port-expansion 1 commit + 5 个 Port 扩展 + 16 个 react/ 类 ChatRunContext 转换。*
