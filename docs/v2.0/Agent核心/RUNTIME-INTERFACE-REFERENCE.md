# D4 运行时层接口参考

> **版本**：v1.0（2026-06-30）
> **Owner**：④ 运行时 + `gnex-agent-service`
> **代码 SSOT**：`libs/gnex-contracts/`（Java `interface` 定义处）
> **契约 SSOT**：[RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md) v2.0
> **架构 SSOT**：[RUNTIME-LAYER.md](./RUNTIME-LAYER.md)  
> **外部系统索引**：[INTELLIGENT-ENGINE-INTERFACES.md](./INTELLIGENT-ENGINE-INTERFACES.md)

本文按**上层/下层**视角列出 D4 运行时层的全部 Port 接口。每个接口包含方法签名、入参出参、前置条件、后置条件、失败语义。

**符号说明**：
- ✓ 必填 | ○ 可选 | ⚠ 条件必填
- 前置 = 调用前必须成立 | 后置 = 调用后保证成立 | 失败 = 异常或异常返回值

---

## 1. 上层接口（D4 暴露，②③⑧ 消费）

### 1.1 核心执行

#### CoordinatorRuntimePort

> 消费方：③ `Orchestrator` | 实现方：④ `AgentRuntime` | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `runCoordinatorReAct` | `systemPrompt` ✓, `userInput` ✓ | `ReActResult` | RC-04 已 bind；RC-05 已 acquire | 返回最终文本 + token 用量；checkpoint COMPLETED/RESUMABLE | 预算拒绝→RC-08 拦截；cancel→`OperationCancelledException`；LLM/工具→ERROR 事件 |
| `runDirectAnswer` | `systemPrompt` ✓, `userInput` ✓ | `ReActResult` | 同上 | 单轮 LLM，无 tool，2-5s 完成 | 同上 |
| `resumeCoordinatorReAct` | `checkpoint` ✓ | `ReActResult` | checkpoint.isResumable()==true | 同 runCoordinatorReAct | checkpoint 非法→`IllegalArgumentException` |
| `publishRoutingToUi` | `match` ○ | void | SSE 已 attach | UI 收到 routing 事件 | SSE 断开→静默丢弃 |

**嵌套类型**：`AgentRoutingMatch(String agentName, String description, double confidence)`

#### AgentRuntimePort

> 消费方：③⑧ | 实现方：④ `AgentRuntime` | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `delegateToWorker` | `targetAgent` ✓, `task` ✓ | `String` | Context.depth < maxDepth；agent 在 ⑤ 可解析 | Worker 最终文本 | agent 不存在→明确异常；超 depth→拒绝 |

#### AgentSyncDelegationPort

> 消费方：③ | 实现方：④ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `delegateToWorker` | `agentName` ✓, `taskDescription` ✓ | `String` | 同 AgentRuntimePort；steeringSupplier 非 null | Worker 单次 ReAct 结果 | 同上 |

---

### 1.2 上下文与并发

#### ChatRunContextPort

> 消费方：②③ | 实现方：④ ThreadLocal | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `create` | — | `ChatRunContext` | — | 新 Context 实例 | — |
| `bind` | `context` ✓ | void | context 非 null | ThreadLocal 绑定完成 | — |
| `unbind` | — | void | 已 bind | ThreadLocal 清除 | — |

#### ChatConcurrencyPort

> 消费方：② | 实现方：④ `MessageQueue` | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `tryAcquireGlobal` | — | `boolean` | — | true=全局槽位已占；false=全局满 | — |
| `tryAcquireSession` | `sessionId` ✓ | `boolean` | — | true=该 session 独占锁已获；false=该 session 正忙 | — |
| `prepareForNewTurn` | `sessionId` ✓ | void | session 锁已 acquire | 清 cancel+steering 队列；保留 follow-up | — |
| `releaseSession` | `sessionId` ✓ | void | — | 该 session 锁释放 | — |
| `releaseGlobal` | — | void | — | 全局槽位释放 | — |

#### ChatInFlightControlPort

> 消费方：② `ChatControlController` | 实现方：glue | 包：`contracts.runtime`
> ⚠ 1.0 接口，2.0 被 SessionLoopPort.fireInbound 替代

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `queueSteering` | `sessionId` ✓, `message` ✓ | void | session 有活跃 run | steering 入队，下 turn PREP 生效 | session 无活跃 run→静默入队（不消费） |
| `queueFollowUp` | `sessionId` ✓, `message` ✓ | void | — | follow-up 入队 | — |
| `cancelBySession` | `sessionId` ✓ | `boolean` | — | true=cancel 信号已设 | — |

#### ChatActiveRunPort

> 消费方：② | 实现方：④ `ActiveRunRegistry` | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `registerRun` | `runId` ✓, `conversationSessionId` ✓, `sseSessionId` ✓ | void | — | run 注册到活跃表 | — |
| `addSubscriber` | `runId` ✓, `sseSessionId` ✓ | `boolean` | run 已注册 | 新 SSE 订阅者加入 | run 不存在→false |
| `unregisterRun` | `runId` ✓ | `Set<String>` | — | run 从活跃表移除；返回所有 sseSessionId | — |
| `isRunActive` | `runId` ✓ | `boolean` | — | true=run 正在执行 | — |
| `findRunIdByConversationSession` | `conversationSessionId` ✓ | `Optional<String>` | — | 该会话的活跃 runId | — |
| `snapshot` | `runId` ✓ | `Optional<ActiveRunSnapshot>` | — | run 快照 | run 不存在→empty |

---

### 1.3 会话与 UI

#### ChatSessionPort

> 消费方：② | 实现方：④ `SessionManager` | 包：`contracts.runtime`
> extends `SessionFollowUpPort`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `startNewSession` | `title` ✓, `mode` ✓, `parentSessionId` ○ | void | — | 新会话创建并激活 | — |
| `activateSession` | `sessionId` ✓, `parentSessionId` ○ | void | session 存在 | session 设为活跃 | session 不存在→异常 |
| `getCurrentSessionMode` | — | `SessionMode` | — | 当前会话模式 | — |
| `applyExecutionMode` / `resetExecutionMode` | — | void | — | 执行模式切换 | — |
| `buildConversationHistoryPrefix` | `sessionId` ○ | `String` | — | 历史消息前缀文本 | — |
| `buildSubtaskContextPrefix` | `sessionId` ○ | `String` | — | 子任务上下文前缀 | — |
| `persistMessage` | `sessionId` ✓, `role` ✓, `content` ✓, `toolName` ○ | void | — | 消息持久化 | — |
| `persistMessageReturningId` | 同上 + 返回 ID | `Long` | — | 消息持久化并返回 ID | — |

#### AgentRuntimeUiPort

> 消费方：② SSE | 实现方：④ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `publishRoutingToUi` | `match` ○ | void | SSE 已 attach | UI 收到 routing 事件 | SSE 断开→静默 |
| `publishAgentInvoke` / `publishAgentFinished` | `agentName` ✓ | void | — | Agent 生命周期事件 | — |
| `publishAgentStatus` | `agentName` ✓, `status` ✓ | void | — | 状态事件 | — |
| `publishInstallStarted` / `publishInstallResult` | `label` ✓, `result` ○ | void | — | 安装进度事件 | — |

#### RunEventPublisher

> 消费方：④ 内部 | 实现方：glue→② SSE | 包：`contracts.access`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `publish` | `sessionId` ✓, `event` ✓ | void | — | 事件推送给所有订阅者 | SSE 断开→静默 |
| `publishIfConnected` | 同上 | `boolean` | — | true=至少一个订阅者收到 | — |
| `isConnected` | `sessionId` ✓ | `boolean` | — | true=有活跃 SSE 连接 | — |

#### AgentEventPort

> 消费方：② SSE | 实现方：④ | 包：`contracts.access`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `emit` | `event` ✓ | void | — | 层级事件推送给 SSE 客户端 | — |

---

### 1.4 委派与治理

#### DelegationControlPort

> 消费方：② | 实现方：④ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listActive` | — | `List<DelegationSummary>` | — | 所有活跃委派列表 | — |
| `findByCancelToken` | `cancelToken` ✓ | `@Nullable DelegationSummary` | — | 对应委派摘要 | — |
| `cancel` | `cancelToken` ✓ | `boolean` | — | true=委派已取消 | token 不存在→false |

#### IsolatedSessionPolicyPort

> 消费方：② | 实现方：⑦ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `shouldDefaultIsolated` | `explicitMode` ○, `agentName` ○, `userText` ✓ | `boolean` | — | true=该会话应使用隔离模式 | — |

#### ProviderTracePort

> 消费方：④ 内部 | 实现方：④ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `injectProtocolMessages` | `messages` ✓, `sessionId` ✓, `modelName` ✓ | `int` | — | 注入的协议消息数 | — |
| `persistFromContext` | `executionContext` ✓, `modelName` ✓ | void | run 已完成 | trace 已持久化 | — |

---

## 2. 下层接口（D4 消费，⑤⑥⑦⑧⑨ 实现）

### 2.1 ③ 编排层

#### ChatOrchestrationPort

> 实现方：③ `Orchestrator` | 包：`contracts.orchestration`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `processStream` | `userInput` ✓, `sseSessionId` ✓ | `String` | RC-05 已 acquire | 编排完成文本 | 编排异常→向上抛 |
| `resumeFromCheckpoint` | `checkpoint` ✓, `sseSessionId` ✓ | `String` | checkpoint 可恢复 | 恢复编排完成文本 | — |

#### OutputChannelPort

> 实现方：③ | 包：`contracts.orchestration`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `recordToolOutput` | `agentId` ✓, `projectId` ✓, `toolName` ✓, `arguments` ✓, `result` ✓, `durationMs` ✓ | void | — | 工具输出记录到 execution_log | — |
| `recordAs` | 同上 + `preferredType` ✓ | void | — | 指定输出类型记录 | — |

#### AgentBudgetPort

> 实现方：③ `AgentBudgetService` | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `checkBudget` | `agentName` ✓, `projectId` ✓ | `@Nullable String` | — | null=允许；非 null=拒绝原因 | — |
| `checkoutTokens` | `agentName` ✓, `projectId` ✓, `tokens` ✓ | `boolean` | — | true=扣费成功 | 扣费失败→false，记审计 |

---

### 2.2 ⑤ 注册层（platform-service）

#### AgentRegistryPort

> 实现方：platform-service | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listAll` | — | `List<AgentRegistryRecord>` | — | 所有已注册 Agent | — |
| `uninstall` | `name` ✓ | `String` | agent 存在 | 卸载结果消息 | agent 不存在→异常 |
| `installFromCanonical` | `canonicalAgent` ✓, `domain` ✓ | `String` | — | 安装结果消息 | 安装失败→异常 |
| `installAllFromPath` | `sourcePath` ✓, `domain` ✓ | `String` | — | 批量安装结果 | — |

#### LlmConfigPort

> 实现方：④ `LLMConfigManager` | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getEffectiveDefaultModel` | — | `String` | — | 当前默认模型名 | — |
| `getMaskedApiKey` | — | `String` | — | 脱敏 API Key | — |
| `getEffectiveBaseUrl` | — | `String` | — | 当前 Base URL | — |
| `getRegisteredModels` | — | `Map<String, LlmModelInfo>` | — | 已注册模型映射 | — |
| `getModelForAgent` | `agentName` ✓ | `String` | — | 该 Agent 使用的模型 | — |
| `getAgentModelOverride` | `agentName` ✓ | `@Nullable String` | — | 该 Agent 模型覆盖值 | — |
| `setDefaultModel` / `setApiKey` / `setBaseUrl` | 对应值 ✓ | void | — | 配置更新 | — |
| `setAgentModel` | `agentName` ✓, `model` ○ | void | — | Agent 模型覆盖设置 | — |
| `registerModel` | `modelName` ✓, `contextWindow` ✓, `provider` ✓ | void | — | 模型注册 | — |
| `registerModelWithEndpoint` | 同上 + `protocol` ✓, `baseUrl` ○ | void | — | 带端点的模型注册 | — |

#### LlmModelCatalogPort

> 实现方：platform-service | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listCatalog` | — | `List<CatalogEntry>` | — | 30 主流模型目录 | — |
| `findByModel` | `modelId` ✓ | `@Nullable CatalogEntry` | — | 目录条目 | — |
| `listProviders` | — | `List<String>` | — | 所有 provider 列表 | — |
| `checkConnectivity` | — | `List<ConnectivityResult>` | — | 每个模型的连通性探测 | 无 API Key→NO_KEY（非失败） |

#### AgentToolBootstrapPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `bootstrap` | `delegationTarget` ✓ | `AgentToolArrays` | Agent 定义已加载 | 返回 3 组 ToolCallback | bootstrap 异常→向上抛 |

#### AgentWorkerToolPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `createAgentTools` | `agentName` ✓ | `ToolCallback[]` | agent 在 ⑤ 可解析 | 该 Agent 的工具集 | agent 不存在→空数组 |

#### AgentWorkerToolConfiguratorPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `configureAgentSafeCallbacks` | `agentSafeCallbacks` ✓ | void | — | Worker 安全工具回调配置完成 | — |

#### ToolHookPort

> 实现方：platform-service `HookExecutor` | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `executeToolHook` | `phase` ✓, `agentName` ✓, `sessionId` ✓, `toolName` ✓, `arguments` ✓, `result` ○ | `ToolHookOutcome` | — | Hook 执行结果（可能修改参数或取消） | Hook 异常→按 ⑤ 策略 |

**嵌套类型**：`ToolHookPhase { PRE_TOOL_USE, POST_TOOL_USE }`、`ToolHookOutcome(String arguments, boolean cancelled)`

---

### 2.3 ⑥ 治理层

#### ConfirmationPort

> 实现方：⑥ | 包：`contracts.governance`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `approve` | `confirmationId` ✓ | `boolean` | confirmation 存在且 PENDING | true=已批准 | ID 不存在→false |
| `reject` | `confirmationId` ✓ | `boolean` | 同上 | true=已拒绝 | 同上 |

#### ToolAuditPort

> 实现方：⑥ | 包：`contracts.governance`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `record` | `ToolAuditRequest` ✓ | void | — | 审计事件已记录（best-effort） | 记录失败→静默 |

#### QualityGatePort

> 实现方：⑥ | 包：`contracts.governance`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `evaluate` | `mode` ✓ | `Report` | — | 质量门禁报告 | — |
| `listQuarantine` | — | `List<QuarantineEntry>` | — | 隔离条目列表 | — |
| `releaseQuarantine` | `testName` ✓ | void | 条目存在 | 隔离释放 | — |

#### EvaluationPort

> 实现方：agent-service | 包：`contracts.governance`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `evaluateSession` | `sessionId` ✓, `knownTools` ○ | `ResultView` | — | 会话评估结果 | — |
| `replaySession` | `originalSessionId` ✓, `config` ✓ | `ReplayComparisonView` | — | 回放对比结果 | — |
| `compareSessions` | `sessionA` ✓, `sessionB` ✓ | `TraceDiffView` | — | 轨迹差异 | — |
| `checkAiAssets` | — | `AssetsCheckReportView` | — | AI 资产检查报告 | — |

---

### 2.4 ⑦ 沙箱层

#### SandboxPort

> 实现方：sandbox-runtime（remote）/ agent-service（local） | 包：`contracts.sandbox`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `execute` | `action` ✓, `timeout` ✓ | `ObservationMessage` | — | 沙箱执行结果 | 超时→异常；沙箱拒绝→错误 observation |
| `pollPendingAction` | `tenantId` ✓, `sandboxId` ✓, `consumerName` ✓ | `Optional<ActionMessage>` | — | 待处理 action | — |
| `transportName` | — | `String` | — | `"local"` 或 `"remote"` | — |

#### SandboxManagementPort

> 实现方：⑦ | 包：`contracts.sandbox`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listProfiles` | — | `ProfileListResponse` | — | 所有沙箱 profile | — |
| `assignProfile` | `agentName` ✓, `archetypeKey` ✓ | `AssignResult` | archetype 存在 | profile 分配结果 | archetype 不存在→`IllegalArgumentException` |

#### LoopWarningPort

> 实现方：④ | 包：`contracts.sandbox`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `emitWarning` | `toolName` ✓, `consecutiveCount` ✓ | void | — | 循环检测警告推送给 UI | — |

---

### 2.5 ⑧ 总线层

#### MessageBusPort

> 实现方：bus-service | 包：`contracts.bus`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `publishAction` | `action` ✓ | void | — | action 已发布 | — |
| `publishObservation` | `observation` ✓ | void | — | observation 已发布 | — |
| `awaitObservation` | `tenantId` ✓, `sandboxId` ✓, `requestId` ✓, `timeout` ✓ | `Optional<ObservationMessage>` | — | 对应 observation 或 empty | — |
| `publish` | `event` ✓ | void | — | 事件已发布 | — |
| `subscribe` / `unsubscribe` | `topicPattern` ✓, `handler` ✓ | void | — | 订阅/取消订阅 | — |
| `pollAction` | `tenantId` ✓, `sandboxId` ✓, `consumerName` ✓ | `Optional<ActionMessage>` | — | 待处理 action | — |
| `transportName` | — | `String` | — | `"database"` / `"redis"` / `"kafka"` | — |

#### AgentCommunicationPort

> 实现方：bus-service | 包：`contracts.bus`

**核心 API**：

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `dispatch` | `DispatchContext` ✓ | `DispatchReceipt` | — | 任务已分发 | 目标 agent 不存在→异常 |
| `await` | `taskId` ✓, `timeout` ✓, `onProgress` ○ | `SyncResult` | — | 同步等待结果 | 超时→status=TIMEOUT |
| `onEvent` | `agentName` ✓, `topicPattern` ✓, `handler` ✓ | `Subscription` | — | 事件监听已注册 | — |
| `cancel` | `taskId` ✓ | `boolean` | — | true=取消已接受 | — |

#### AgentMessageBusPort

> 实现方：bus-service | 包：`contracts.messagebus`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `subscribe` / `unsubscribe` | `agentName` ✓, `topicPattern` ✓, `competition` ⚠ | `Subscription` / void | — | 订阅/取消 | — |
| `listSubscriptions` | `agentName` ○ | `List<Subscription>` | — | 订阅列表 | — |
| `pauseSubscription` / `resumeSubscription` | `id` ✓ | `Subscription` | 订阅存在 | 暂停/恢复 | — |
| `backpressureStatus` | — | `BackpressureStatus` | — | 背压状态 | — |
| `publish` | `senderAgent` ✓, `topic` ✓, `payload` ✓, `verifyTopic` ○, `verifyBy` ○ | `PublishResult` | — | 发布结果 | — |
| `consume` | `agentName` ✓, `blocking` ✓, `dispatch` ✓ | `ConsumeResult` | — | 消费结果 | — |
| `deadLetterStats` | — | `DeadLetterStats` | — | 死信统计 | — |
| `listMessages` | `targetAgent` ○, `status` ○, `page` ✓, `pageSize` ✓ | `MessagePage` | — | 消息分页 | — |
| `requeueMessage` | `messageId` ✓ | `Message` | — | 重新入队 | — |
| `batchRequeue` / `batchArchive` | `messageIds` ✓ | `BatchOperationResult` | — | 批量操作结果 | — |
| `stopAgent` / `resumeAgent` | `agentName` ✓ | `StopResult` / void | — | 停止/恢复消费 | — |

---

### 2.6 ⑨ 数据层（会话/诊断/记忆/工作区）

#### ConversationAccessPort

> 实现方：agent-service | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getSessionForUser` | `sessionId` ✓, `userId` ✓ | `ConversationSessionRecord` | session 存在 | 会话记录 | 无权限→异常 |
| `createSession` | `title` ✓, `mode` ✓, `createdBy` ✓ | `ConversationSessionRecord` | — | 新会话记录 | — |
| `listSessions` | `limit` ✓, `userId` ✓ | `List<ConversationSessionRecord>` | — | 会话列表 | — |
| `updateTitleForUser` | `sessionId` ✓, `userId` ✓, `title` ✓ | `ConversationSessionRecord` | — | 标题已更新 | — |
| `setPinnedForUser` | `sessionId` ✓, `userId` ✓, `pinned` ✓ | `ConversationSessionRecord` | — | 置顶状态已更新 | — |
| `deleteSessionForUser` | `sessionId` ✓, `userId` ✓ | `boolean` | — | true=已删除 | — |
| `getSession` | `sessionId` ✓ | `ConversationSessionRecord` | — | 会话记录 | — |
| `getSessionMessages` | `sessionId` ✓ | `List<ConversationMessageRecord>` | — | 消息列表 | — |
| `getBranchMessages` | `sessionId` ✓, `branchId` ✓ | `List<ConversationMessageRecord>` | — | 分支消息列表 | — |
| `addMessage` | `sessionId` ✓, `role` ✓, `content` ✓, `toolName` ○ | `Long` | — | 消息 ID | — |
| `updateMessageContent` | `messageId` ✓, `content` ✓ | void | — | 消息内容已更新 | — |
| `forkFromMessage` | `sessionId` ✓, `messageId` ✓ | `String` | — | 新分支 ID | — |
| `listBranches` | `sessionId` ✓ | `List<String>` | — | 分支 ID 列表 | — |
| `summarizeBranch` | `sessionId` ✓, `branchId` ✓ | `BranchSummaryRecord` | — | 分支摘要 | — |

#### SessionUsagePort

> 实现方：④ `UsageTracker` | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getSessionUsage` | `sessionId` ✓ | `Map<String, Object>` | — | 会话 token 用量 | — |

#### ModelPricingPort

> 实现方：④ `UsageTracker` | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getModelPrices` | — | `Map<String, Double>` | — | 模型价格映射 | — |
| `setModelPrice` | `model` ✓, `price` ✓ | void | — | 价格已设置 | — |

#### OutputAdoptionPort

> 实现方：agent-service | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `record` | `RecordRequest` ✓ | `Adoption` | — | 采纳记录 | — |
| `findBySession` | `sessionId` ✓ | `List<Adoption>` | — | 采纳列表 | — |
| `findByMessageId` | `messageId` ✓ | `@Nullable Adoption` | — | 采纳记录 | — |
| `findStats` | `tenantId` ○, `from` ○, `to` ○ | `Map<String, Long>` | — | 统计数据 | — |

#### SessionArchiveQueryPort

> 实现方：agent-service | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `findByTopic` | `keyword` ✓ | `List<SessionArchiveRecord>` | — | 主题匹配的归档 | — |
| `findRecent` | `since` ✓ | `List<SessionArchiveRecord>` | — | 时间范围归档 | — |

#### SessionArtifactPort

> 实现方：agent-service | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `recordPath` | `sessionId` ✓, `path` ✓ | void | — | 产物路径已记录 | — |
| `bindOrphanArtifactsSince` | `sessionId` ✓, `messageId` ✓, `since` ✓ | void | — | 孤立产物已绑定 | — |
| `resolvePathsByMessage` | `sessionId` ✓, `messages` ✓ | `Map<Long, List<String>>` | — | 按消息的产物路径映射 | — |
| `listPaths` | `sessionId` ✓ | `Set<String>` | — | 所有产物路径 | — |

#### AgentRunEventQueryPort

> 实现方：agent-service | 包：`contracts.diagnostics`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `findByRunId` | `runId` ✓ | `List<RunEvent>` | — | 扁平事件列表 | — |
| `findTreeByRunId` | `runId` ✓ | `List<RunEvent>` | — | 树形事件列表 | — |
| `findContextPacksByRunId` | `runId` ✓ | `List<ContextPack>` | — | 上下文压缩包 | — |
| `findBySessionId` | `sessionId` ✓, `limit` ✓ | `List<RunEvent>` | — | 会话事件列表 | — |
| `findDecisions` | `limit` ✓ | `List<RunEvent>` | — | 决策事件列表 | — |
| `listRecentRuns` | `limit` ✓, `projectId` ○ | `List<RunSummary>` | — | 最近 run 摘要 | — |
| `listRecentRuns` (date range) | `from` ✓, `to` ✓, `limit` ✓, `projectId` ○ | `List<RunSummary>` | — | 日期范围 run 摘要 | — |
| `findRunWithProviderTrace` | `runId` ✓ | `List<RunEventWithTrace>` | — | 带 provider trace 的事件 | — |

#### OperationsMetricsPort

> 实现方：agent-service | 包：`contracts.diagnostics`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getMetrics` | `from` ✓, `to` ✓, `projectId` ○ | `OperationsMetricsResponse` | — | 运维指标 | — |
| `getTrends` | `from` ✓, `to` ✓, `projectId` ○ | `MetricsTrendsResponse` | — | 趋势数据 | — |
| `getModelBreakdown` | `from` ✓, `to` ✓, `projectId` ○ | `List<ModelBreakdownPoint>` | — | 模型用量分解 | — |

#### RunDiagnosticsPort

> 实现方：agent-service | 包：`contracts.diagnostics`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getLatestForSession` | `sessionId` ✓ | `Optional<RunSummary>` | — | 最新 run 诊断摘要 | — |
| `finalizeRun` | `RunFinalizeRequest` ✓ | `RunSummary` | — | run 最终摘要 | — |

#### RunPromptLabelQueryPort

> 实现方：agent-service | 包：`contracts.diagnostics`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `findRunLabelsBySessionId` | `sessionId` ✓ | `List<RunLabel>` | — | 会话 run 标签 | — |
| `findUserPromptByRunId` | `runId` ✓ | `Optional<String>` | — | 用户输入 prompt | — |

#### MemoryQueryPort

> 实现方：agent-service | 包：`contracts.memory`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `query` | `q` ○, `source` ○, `page` ✓, `pageSize` ✓ | `Page` | — | L1 记忆分页 | — |
| `delete` | `id` ✓ | `boolean` | — | true=已删除 | — |

#### StatePort

> 实现方：待实现（Phase 7） | 包：`contracts.state`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getSessionAttribute` | `tenantId` ✓, `sessionId` ✓, `key` ✓ | `Optional<String>` | — | session 属性值 | — |
| `putSessionAttribute` | `tenantId` ✓, `sessionId` ✓, `key` ✓, `value` ✓, `ttl` ✓ | void | — | 属性已写入 | — |
| `deleteSessionAttributes` | `tenantId` ✓, `sessionId` ✓ | void | — | 所有属性已删除 | — |
| `loadCheckpoint` | `tenantId` ✓, `runId` ✓ | `Optional<ReActCheckpoint>` | — | checkpoint | — |
| `saveCheckpoint` | `tenantId` ✓, `checkpoint` ✓ | void | — | checkpoint 已持久化 | — |
| `backendName` | — | `String` | — | `"sqlite"` / `"redis-postgres"` | — |

#### IsolatedWorkSpacePort

> 实现方：⑦ | 包：`contracts.workspace`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listByStatus` | `status` ✓, `limit` ✓ | `List<Workspace>` | — | 状态过滤的工作区 | — |
| `listByProjectId` | `projectId` ✓, `limit` ✓ | `List<Workspace>` | — | 项目工作区 | — |
| `listPendingReview` | — | `List<Workspace>` | — | 待审核工作区 | — |
| `create` | `sourcePath` ✓, `sessionId` ✓ | `Workspace` | — | 隔离工作区已创建 | 创建失败→异常 |
| `findByWorkspaceId` | `workspaceId` ✓ | `@Nullable Workspace` | — | 工作区 | — |
| `refreshDiff` | `workspaceId` ✓ | `Workspace` | workspace 存在 | 刷新 diff | — |
| `apply` / `discard` | `workspaceId` ✓ | `Workspace` | workspace 存在 | 应用/丢弃 | 操作失败→异常 |

#### WorkspaceArtifactPort

> 实现方：agent-service | 包：`contracts.workspace`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listArtifacts` | — | `List<ArtifactView>` | — | 全部产物 | — |
| `listArtifactsForSession` | `sessionId` ✓ | `List<ArtifactView>` | — | 会话产物 | — |
| `uploadFile` | `UploadRequest` ✓ | `ArtifactView` | — | 上传后产物视图 | — |
| `readPreview` | `relativePath` ✓ | `PreviewView` | 文件存在 | 预览内容 | — |
| `openForDownload` / `openForInlinePreview` | `relativePath` ✓ | `Resource` | 文件存在 | 文件资源 | — |
| `mimeTypeForPath` | `relativePath` ✓ | `String` | — | MIME 类型 | — |

---

## 3. SessionLoop 2.0 新增接口

> 详见 [RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md) §8。以下为快速参考。

### SessionLoopPort

> 实现方：agent-service | 消费方：②③⑧ | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `fireInbound` | `sessionId` ✓, `kind` ✓, `payload` ✓ | void | — | 事件入队，loop 唤醒 | — |
| `wakeUp` | `sessionId` ✓ | void | — | IDLE/YIELDING loop 被唤醒 | — |
| `isBusy` | `sessionId` ✓ | `boolean` | — | true=session 正在处理 | — |
| `attachSse` | `sessionId` ✓, `sseSessionId` ✓ | void | — | SSE 连接绑定到 session | — |
| `detachSse` | `sessionId` ✓ | void | — | SSE 连接触绑，loop 继续 | — |
| `getChannelStatus` | `sessionId` ✓ | `ChannelStatus` | — | channel 状态 | — |

### InboundKind

```java
CANCEL(0), STEERING(1), USER_TURN(2), FOLLOW_UP(3), BUS_TASK(4)
```

### TurnResult → LoopControlDecision

| TurnResult | → LoopControlDecision | 条件 |
|------------|----------------------|------|
| REACT_DONE | COMPLETE | 队列空 |
| REACT_DONE | RUN_ONE_TURN | 队列有事件 |
| TOOL_CALL_PENDING | RUN_ONE_TURN | — |
| BUDGET_EXHAUSTED | YIELD_SLICE | — |
| ERROR | COMPLETE / RUN_ONE_TURN | 取决于重试 |

### ChannelStatus

```
IDLE → PROCESSING → YIELDING → PROCESSING (续跑)
                  → COMPLETED
                  → CANCELLED
                  → STALLED → PROCESSING (Watchdog)
                  → CANCELLED (超限)
```

---

## 4. DTO 速查表

### runtime

| 类型 | 字段 |
|------|------|
| `ReActResult` | `text: String`, `totalTokenUsage: int` |
| `ReActCheckpoint` | `id: long`, `runId`, `sessionId`, `tenantId`, `nextTurnIndex`, `maxTurns`, `totalTokenUsage`, `effectiveModel`, `requestedModel`, `userInput`, `messagesJson`, `status` |
| `ChatRunContext` | 可变接口：`runId`, `sessionId`, `projectId`, `agentName`, `sseSessionId`, `userId`, `depth/maxDepth`, `currentJobId`, `presetOverride` 等 |
| `AgentToolArrays` | `staticRiskAwareCallbacks`, `coordinatorCallbacks`, `agentSafeCallbacks` (均为 `ToolCallback[]`) |
| `DelegationRecords.DelegationSummary` | `cancelToken`, `agentName`, `parentRunId`, `cancelled`, `startedAt` |
| `SessionMode` | `INTERACTIVE`, `BACKGROUND`, `SUBTASK`, `ISOLATED` |

### access

| 类型 | 字段 |
|------|------|
| `SseEvent` | `type: SseEventType`, `sessionId`, `payload`, `runId`, `seq` + 多种 Payload record |
| `AgentEvent` | `type: EventType`, `sessionId`, `payload` + 多种 Payload record |
| `RunSummary` | `traceId`, `sessionId`, `runId`, `status`, `durationMs`, `toolCallCount`, `tokenUsage` 等 |

### registry

| 类型 | 字段 |
|------|------|
| `LlmModelInfo` | `name`, `contextWindow`, `provider` |
| `LlmModelCatalogRecords.CatalogEntry` | `modelId`, `provider`, `baseUrl`, `contextWindow`, `protocol`, `pricePerMillion`, `keyEnv` |
| `LlmModelCatalogRecords.ConnectivityResult` | `modelId`, `provider`, `status`, `message`, `httpStatus` |
| `AgentRegistryRecord` | `name`, `description`, `source`, `domain`, `status` |
| `ToolHookPort.ToolHookOutcome` | `arguments`, `cancelled` |
| `ToolHookPort.ToolHookPhase` | `PRE_TOOL_USE`, `POST_TOOL_USE` |

### bus

| 类型 | 字段 |
|------|------|
| `ActionMessage` | `tenantId`, `sandboxId`, `requestId`, `toolName`, `arguments`, `riskLevel` 等 |
| `ObservationMessage` | `requestId`, `result`, `error`, `durationMs` 等 |
| `BusEventMessage` | `topic`, `senderAgent`, `payload`, `timestamp` 等 |
| `AgentCommunicationRecords.DispatchContext` | `sender`, `targetHint`, `task`, `strategy`, `timeout`, `metadata`（**v2.0 规划新增**：`goal` 见 [AGENT-SERVICE-DESIGN §5.3](./AGENT-SERVICE-DESIGN.md)；`lineage` 用于环检测，见 [V1-CODE-REALITY §6](./V1-CODE-REALITY.md)） |
| `AgentCommunicationRecords.SyncResult` | `status`, `resultText` |

### conversation

| 类型 | 字段 |
|------|------|
| `ConversationSessionRecord` | `id`, `title`, `status`, `mode`, `projectId`, `createdBy`, `tenantId`, `pinned` 等 |
| `ConversationMessageRecord` | `id`, `sessionId`, `role`, `content`, `toolName`, `compacted`, `parentId`, `branchId`, `artifactPaths` |
| `SessionArchiveRecord` | `id`, `sessionId`, `title`, `summary`, `keyTopics`, `modelUsed`, `totalTokens` 等 |

### diagnostics

| 类型 | 字段 |
|------|------|
| `RunEventRecords.RunEvent` | `id`, `runId`, `sessionId`, `eventType`, `eventName`, `parentEventId` 等 |
| `RunEventRecords.RunSummary` | `runId`, `sessionId`, `status`, `startedAt`, `durationMs`, `tokenUsage` 等 |
| `RunFinalizeRequest` | `sessionId`, `runId`, `sseSessionId`, `status`, `durationMs`, `errorMessage` |

---

## 5. 接口统计

| 类别 | 接口数 | 方法数 |
|------|--------|--------|
| **上层暴露** | 15 | ~65 |
| **下层消费** | 34 | ~140 |
| **SessionLoop 2.0 新增** | 6（1 interface + 5 type） | 6 |
| **合计** | 55 | ~211 |

---

*本文档为 D4 运行时层接口参考；与 gnex-contracts 源码冲突时以源码为准。*
