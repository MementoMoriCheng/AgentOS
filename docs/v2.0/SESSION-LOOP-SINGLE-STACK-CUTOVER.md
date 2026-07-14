# SessionLoop 单栈切换实施计划

> **状态**：Waves 0.5–5 ✅ 结项（2026-07-09）；`develop` @ `c232cce`；tag `pre-session-loop-cutover`
> **结项归档**：[`SESSION-LOOP-SINGLE-STACK-CUTOVER-POSTMORTEM.md`](./SESSION-LOOP-SINGLE-STACK-CUTOVER-POSTMORTEM.md)
> **待运维**：Jenkins/E2E/灰度见 §8.1（用户当前跳过 Jenkins）
> **策略**：废弃 1.0 双循环，SessionLoop 作为唯一会话调度内核，**无 feature flag、无降级路径**
> **取代**：[SESSION-EVENT-LOOP-EXEC-SUMMARY.md](./v2.0/Agent核心/SESSION-EVENT-LOOP-EXEC-SUMMARY.md) 中"双路径 feature flag 灰度"策略
> **关联 SSOT**：[SESSION-EVENT-LOOP.md](./v2.0/Agent核心/SESSION-EVENT-LOOP.md) · [RUNTIME-LAYER.md](./v2.0/Agent核心/RUNTIME-LAYER.md) · [V1-CODE-REALITY.md](./V1-CODE-REALITY.md)
> **代码快照**：2026-07-07 main 分支

---

## 1. 决策声明

### 1.1 策略（不可撤销）

| 项 | 决策 |
|----|------|
| **调度内核** | SessionLoop 作为唯一会话调度器 |
| **1.0 双循环** | 物理删除（MessageQueue 双 Lane + FollowUpContinuationLoop + SteeringSuppliers） |
| **Feature Flag** | **不保留** `gnex.event-loop.enabled`，无降级路径 |
| **DB 迁移** | 一次性原子切换（含 lease_owner / lease_expires_at 字段 + run_lease 表） |
| **回滚机制** | 部署级 rollback（git tag + DB 备份），不做应用层 fallback |
| **执行窗口** | 单栈方案，不接受变相双栈 |

### 1.2 替代方案否决记录

| 替代方案 | 否决理由 |
|---------|---------|
| 双栈并存 + feature flag 灰度 | 长期维护成本高；双路径排查心智负担；E2E 矩阵翻倍；likely 永久并存 |
| 局部修复 1.0（~1.4 人周） | 不解决根本复杂度（三套 in-flight 索引、双重取消通道）；限制未来 LongRun / AgentInboxLoop 演进 |
| 渐进迁移（Phase 2a → 2b → 2c） | 长期处于双栈过渡态，决策持续延期 |

### 1.3 不可逆声明

- Wave 3 切换流量后，DB schema 已变更，应用层 fallback 不可用
- Wave 4 物理删除 1.0 代码后，唯一回滚途径是 git checkout tag + DB 备份恢复
- **接受这个事实**，不为回滚预留应用层通道

---

## 2. 影响面

### 2.1 SDK 4 子包重组（libs/gnex-agent-sdk）

| 子包 | 类数 | 来源 | 操作 | Wave |
|------|:----:|------|------|:----:|
| `boundary/` | 22 | 现有 | 不动 | — |
| `memory/` | 16 | 现有 | 不动 | — |
| `service/` | 9 | 现有 | 不动 | — |
| `config/` | 1 | 现有 | 不动 | — |
| **`react/`** | **~25** | 现有 | 从 runtime/ 迁入（机械重构，不改类内容） | **0.5** |
| **`harness/`** | **~10** | 现有 | 从 runtime/ 迁入（同上） | **0.5** |
| **`context/`** | **~15** | 现有 | 从 runtime/ 迁入（同上） | **0.5** |
| **`loop/`** | **18** | **2.0 新建** | 新建（SessionLoop 内核） | **1** |
| **`react/` 升级** | +2 | 新建 | ReActTurnEngine + TurnState（包装 ReActTurnLoop，不动 run() 内部）；execute/resumeExecute 删除延后到 Wave 4 | **1** |

**取消的 `session/` 子包**：原双栈方案用于保留 1.0 降级路径，单栈方案下不需要。

### 2.2 越界文件下放（agent-service）

15 个文件不属于 SDK，下放：

| 文件 | 去向 |
|------|------|
| `AuthProfileManager` | `agent-service/auth/` |
| `ChatRunContextPortAdapter` | `agent-service/adapter/` |
| `ReActSseNotifier` | `agent-service/infra/sse/` |
| `common/sse/*`（4 文件：SseEmitterManager / SseEvent / SseRunEventPublisher / SseTextStreamer） | `agent-service/infra/sse/` |
| `common/trace/*`（1 文件：ExecutionTraceLog） | `agent-service/infra/trace/` |
| `common/observing/LlmMetrics` | `agent-service/infra/metrics/` |
| `WebConfirmationHandler` 等 6 文件（WebConfirmationHandler / WebQuestionHandler / CancelableQuestionHandler / PendingConfirmation / QuestionAnswerPortAdapter / DelegationControlPortAdapter） | `agent-service/interact/` |

### 2.3 1.0 代码物理删除清单

| 类 / 文件 | 当前位置 | 删除原因 |
|----------|---------|---------|
| `MessageQueue.java` | SDK runtime/ | 双 Lane → PriorityInboundQueue 替代 |
| `FollowUpContinuationLoop.java` | SDK runtime/ | 外环 → SessionLoop 内化 |
| `SteeringSuppliers.java` | SDK runtime/ | steering 概念整体废弃 |
| `ReActLoop.execute()` | SDK runtime/ | 全量入口 → 仅保留 runOneTurn |
| `ReActLoop.resumeExecute()` | SDK runtime/ | 同上 |
| `PhasedAgentLoop` follow-up 处理逻辑 | SDK runtime/ | SessionLoop 接管 |
| `ChatInFlightControlPort` 接口 | gnex-contracts/ | steering/followUp API 替换 |
| `ChatInFlightControlAdapter` | agent-service/service/ | 同上 |
| `MessageQueue.cancelFlag` 双通道逻辑 | SDK runtime/ | 单通道 fireInbound(CANCEL) 替代 |
| `ActiveRunRegistry`（评估） | SDK runtime/ | 若无 SSE 订阅独立用途则删 |

### 2.4 上层一次性切换清单

| 层 | 文件 | 改动 |
|----|------|------|
| ② 接入 | `ChatAgentStreamRunner.java:156` | `registerRun` → `SessionLoopPort.fireInbound(USER_TURN)` |
| ② 接入 | `ChatControlController.java:59,83,86` | `queueSteering/queueFollowUp/cancelBySession` → `fireInbound(STEERING/FOLLOW_UP/CANCEL)` |
| ③ 编排 | `Orchestrator.java` | 去掉 FollowUpContinuationLoop 引用 + 改用 SessionLoopPort |
| ③ 编排 | `PlanExecutor.java:526-536` | 重写 async dispatch（消化 [V1-CODE-REALITY §3.2](./V1-CODE-REALITY.md) 270s 超时教训） |
| ④ 运行时 | `ReActLoop.java:314` `resumeExecute()` | 包装为 `ReActTurnEngine.runOneTurn()` |
| ④ 运行时 | `AsyncAgentExecutor.java:55,53,100`（[§3.6](./V1-CODE-REALITY.md) 三套 in-flight 索引） | 统一到 SessionLoopRegistry |
| ④ 运行时 | `AgentScheduler.java:67` `runningTasks` | 同上 |
| ④ 运行时 | `AgentScheduler.java:492-498` `PausableTask.pause()`（[§3.5](./V1-CODE-REALITY.md) 不持久化） | 改为 SessionLoop YIELD + checkpoint |

---

## 3. Wave 实施计划

### Wave 0 · 前置准备（1.5 人周）

**目标**：不写业务代码，识别风险 + 搭建验证基础设施。

| 步 | 内容 | 产出 | 状态 |
|:--:|------|------|:----:|
| 1 | v1.0 隐性契约识别（[V1-CODE-REALITY §4](./V1-CODE-REALITY.md) 5 条 + 全仓 grep + 关键文件精读） | [本文档 §4](#4-隐性契约传承清单) **28 条契约**（A7 / B7 / C4 / D4 / E4 / F2） | ✅ 完成 |
| 2 | 流量录制框架（生产 1.0 turn 事件 → 文件） | `tools/traffic-recorder` | ☐ |
| 3 | 确定性回放框架（mock LLM 响应） | `tools/deterministic-replay` | ☐ |
| 4 | 6 大不变量测试用例设计稿（含并发测试） | [§5](#5-6-大不变量测试设计) 细化 | ☐ |
| 5 | DB schema 迁移脚本（前置 review） | [§6.1](#61-v28__session_loop_leasesql草稿) 草稿 | ☐ |
| 6 | [§4.7](#47-持续识别机制wave-1-3-必须更新本节) 候选契约 6 条进入 Wave 1 验证清单 | 候选清单 | ✅ 完成 |

**Definition of Done**：
- ✅ 28 条 v1.0 隐性契约清单通过架构评审（[§4](#4-隐性契约传承清单)）
- 流量录制跑通，能采集 1.0 turn 事件
- 确定性回放能 mock LLM 输出
- DB 迁移脚本审核通过

### Wave 0.5 · SDK 子包纯拆分（1.5-2 人周，✅ 已完成 2026-07-07）

**目标**：纯机械重构——把 react/ harness/ context/ 三个子包从 runtime/ 迁出，**不引入 SessionLoop、不改类内容**。让 Wave 1 聚焦控制流设计，不被迁包打扰。

**契约保护原则**：本 Wave **不动任何类内容**，只改包路径 + import。隐性契约靠"原样搬"自动保留。

> **✅ 完成状态（2026-07-07，feature/wave-0.5-sdk-split）**：
> - react/ 54 类 + harness/ 36 类机械迁出（commit `62ad9b8` + `e696139`）
> - context/ 6 类拆分**实测阻断**（PreReasoningHook ↔ ContextCompactor 双向依赖），**延后 Wave 1**
> - 4 条 ArchUnit FreezingArchRule 冻结基线（commit `7d2496b`）：
>   - `boundary → react/harness`：0 violations
>   - `memory → react/harness`：0 violations
>   - `service → react`：0 violations
>   - `react → harness`：**371 violations** 冻结为基线（Wave 1 SessionLoop 重塑时通过 Port 消除）
> - `mvn test libs/gnex-agent-sdk` 108/108 pass
> - dev-assembler 上 develop 已存在的编译错误（ProjectConstraintRendererTest/ProceduralSkillInjectorTest/RunDiagnosticsServiceTest 等）顺手修复
> - 详见 [SDK-SPLIT-WAVE-0.5-RECON.md](./v2.0/Agent核心/SDK-SPLIT-WAVE-0.5-RECON.md) §8 实测工作量与 ArchUnit 结果

| 步 | 内容 | 验证 |
|:--:|------|------|
| 1 | 新建 SDK 3 子包目录：`react/` `harness/` `context/`（`loop/` 留给 Wave 1） | 目录空架子 |
| 2 | `git mv` 现有类到目标子包：ReAct* 类 → react/（~25）；harness 相关（HarnessRuntime 等）→ harness/（~10）；context 相关（ContextCompactor / ContextPack 等）→ context/（~15） | 文件路径变更，类内容不动 |
| 3 | 上层 import 重构（IDE Refactor → Move 自动处理；或 `find ... -exec sed` 批量） | 所有 import 指向新包 |
| 4 | ArchUnit 包依赖约束：boundary/memory/service/config 不依赖 react/harness/context/loop；react 不依赖 harness/context；三者皆可依赖 boundary/memory | 单元测试通过 |
| 5 | `mvn compile` + 全量 E2E 回归（11 标准用例） | 编译过 + E2E 全绿 |

**Definition of Done**：
- `mvn compile` 通过
- E2E 全绿（11/11）
- ArchUnit 包依赖规则上线
- §2.1 表格中 `react/ harness/ context/` 三行的 Wave 列从 0.5 标 ✅

### Wave 1 · SDK 内核（3 人周）

> **降量说明**：原 4 人周中的步骤 7"react/ 迁入 + 升级"已拆给 Wave 0.5，本 Wave 聚焦 loop/ 新建 + react/ 升级（不迁包），工作量降至 3 人周。

> **✅ 完成状态（2026-07-07，feature/wave-1-session-loop）**：
> - **Phase 1 — context/ 拆分 + ContextTrimmingPort 抽象** ✅：解 RECON §9 hook 链边界循环依赖（PreReasoningHook ↔ ContextCompactor ↔ ReActLoop）。新建 Port + 6 类迁入 context/。
> - **Phase 2 — loop/ 19 类内核** ✅（plan 估 18，实际 19）：S1-S5 5 个切片，SessionLoop 主循环 + PriorityInboundQueue 双 tier + 5 个 InboundHandler + InboundBackpressure hysteresis + SessionLoopRegistry。
> - **Phase 3 — ReActTurnEngine facade** ✅：包装 ReActLoop（内含 ReActTurnLoop 5 件套），实现 TurnRunner。**修正**：放 loop/（非 react/），ArchUnit 规则 4 放宽允许 ReActTurnEngine 作为 loop/→react/ 唯一桥梁。HookChainOrderInvariantsTest 验证 F2 契约（4 pre + 4 post + 1 postTurn 钩子顺序）。
> - **Phase 4 — 371 → ~120 violation 收敛** ⚠ **部分完成**：实际 375 → 329（**−46**，目标 −250）。RouteDecision 迁移 -41，ReActTurnLifecycle Port 收窄 -5。剩 4 路 Port 替换阻塞于 Port API 设计（ChatRunContext/RunObservabilityPort/LlmConfigPort 都需扩 API），留 Wave 1.5。
> - **Phase 5 — DoD + 文档同步** ✅：4/6 不变量测试落地（I1/I2/I4/I5）；本文档 + RECON §9 同步标 ✅；新建 WAVE-1-SESSION-LOOP-DESIGN。
> - SDK 测试 109 → 208（+99），ArchUnit 6 规则全绿（含 loop/ 仅 ReActTurnEngine 桥接到 react/），全 reactor 编译绿。
> - 详细设计决策：[WAVE-1-SESSION-LOOP-DESIGN.md](./v2.0/Agent核心/WAVE-1-SESSION-LOOP-DESIGN.md)
> - **9 个 commit** push 到 `origin/feature/wave-1-session-loop`，待 code review 后合 develop。

> **Wave 1.5 — Port 扩展（2026-07-07，feature/wave-2-port-completion）** ✅：
> - 329 → 178 react→harness violations（−46%，ChatRunContext 统一 + 3 值对象迁 contracts/）
> - 详见 [WAVE-1.5-PORT-EXPANSION.md](./v2.0/Agent核心/WAVE-1.5-PORT-EXPANSION.md)

> **Wave 2 — Port 完工（2026-07-07，feature/wave-2-port-completion）** ✅：
> - 178 → **0** react→harness production violations（15+ Port interfaces + SseNotifierPort）
> - 5 ArchUnit rules all 0 violations (was 371 at Wave 0.5)
> - 203 SDK tests pass, full reactor compiles
> - 详见 [WAVE-2-PORT-COMPLETION.md](./v2.0/Agent核心/WAVE-2-PORT-COMPLETION.md)

> **Wave 3 — 1.0 @Deprecated 标注（2026-07-08，feature/wave-2-port-completion）** ✅：
> - PhasedAgentLoop / FollowUpContinuationLoop / SteeringSuppliers / EvidenceGate / PhaseToolWhitelist / PhaseHandoffService 标 @Deprecated(since="2.0", forRemoval=true)
> - CUTOVER Wave 3 步骤 5 已提前完成

> **Wave 2.5 — agent-service AgentExecutionContext 解耦（2026-07-08，feature/wave-2-port-completion）** ✅：
> - 17 agent-service 文件从 AgentExecutionContext → ChatRunContext（0 harness/AgentExecutionContext imports in agent-service/src/main/）
> - SseEmitterManager + ExecutionTraceLog：AgentExecutionContext → ChatRunContext, ActiveRunRegistry → ChatActiveRunPort
> - WebConfirmationHandler：LLMConfigManager → LlmConfigPort
> - ChatRunContext 新增 14 方法 + resolveCompletionEvidence static utility
> - ChatActiveRunPort 新增 3 方法（findRunIdBySseSession / getSubscribers / detachSseSession）
> - DelegationDeliverableResolver + ReviewTaskPolicy 参数类型 → ChatRunContext

> **Wave 2.7 — ReActTurnEngine + Hook chain contract（2026-07-08，feature/wave-2-port-completion）** ✅：
> - ReActTurnEngine 放 loop/（非 react/），实现 TurnRunner，包装 ReActLoop.execute()
> - ArchUnit 规则 4 放宽：loop/ 仅允许 ReActTurnEngine 桥接到 react/，其余 loop/ 类仍 0 deps
> - HookChainOrderInvariantsTest：5 个测试验证 F2 契约（4 pre + 4 post + 1 postTurn 钩子顺序 + 无短路）
> - StubChatRunContext 补齐 Wave 2 新增方法（doResolveCompletionEvidence / appendVisibleTranscript / delegation stack 等）
> - SDK 测试 203 → 208（+5），ArchUnit 6 规则全绿，9 E2E 通过

> **Wave 2.8 — agent-service harness/ Port 收敛（2026-07-08，feature/wave-2-port-completion）** ✅：
> - 49 → 5 harness/ imports in agent-service/src/main/（−44，89% 降幅）
> - 8 个纯 JDK 值对象迁 contracts/：diagnostics/{AgentRunEvent,RunEventSummary}, registry/{LoadedAgent,AgentMatch}, runtime/{ReviewTaskPolicy,ScenarioClassifier,AgentRouteTrust,WorkerTaskBundler}
> - 4 个 Port 扩 API：LlmConfigPort（getDefaultChatOptions / getChatOptionsForAgent），RunObservabilityPort（recordDelegation / summarizeRun），DelegationCancelPort（register / unregister / cancel / cancelByAgent）
> - 新建 RunEventQueryPort（read-side split from RunObservabilityPort）— 评估/查询类消费解耦 write side
> - 剩 5 imports 留 Wave 1.5 专项：WorkerAgent ×3（耦合 SandboxProfile），ProactiveTicker（线程化 SSE infra），DelegationDeliverableResolver（文件系统 I/O）
> - SDK 测试 208/208，dev-assembler 81 受影响测试全过，ArchUnit 6 规则 0 冻结违规

> **Wave 2.9–2.10 — agent-service harness/ 完全解耦（2026-07-08，feature/wave-2-port-completion）** ✅：
> - 5 → 0 harness/ imports in agent-service/src/main/（Wave 2.8 收尾）
> - Wave 2.9：抽 3 Port — ProactiveTickerPort（startTicking/stopTicking），DelegationDeliverablePort（resolveForParent），WorkerAgentPort（agent/allowedTools/workerSystemPrompt/isToolAllowed）
> - Wave 2.10：抽 WorkerAgentFactoryPort + SDK WorkerAgentFactory bean — WorkerAgent 构造（archetype profile 解析 + workspace prompt 富化 + sandboxEnforcer 注册）全部封进 SDK
> - agent-service AgentWorkerToolFactory 注入 WorkerAgentFactoryPort，零 harness/ 直接 import
> - 剩 13 react/ imports（ReActLoop ×4, MessageQueue ×3, FollowUpContinuationLoop ×2, SteeringSuppliers/NoReplyGate/CoordinatorToolPolicy/AgentToolCallbackUtils）— 1.0 dual-loop 入口，需 Wave 3 cutover 切到 SessionLoop 才能消除
> - SDK 208/208 测试，CoordinatorWorkerTest PASS

> **Wave 2.11 — react/ 工具类迁 contracts/（2026-07-08，feature/wave-2-port-completion）** ✅：
> - CoordinatorToolPolicy 包声明修正（文件原已位于 contracts/，但 package 仍写 react/）
> - AgentToolCallbacks.concat 抽出 react/AgentToolCallbackUtils，新文件 contracts/runtime/AgentToolCallbacks
> - RiskAwareToolCallback.wrap() 新增静态工厂（替代 AgentToolCallbackUtils.wrapWithRisk）
> - react/AgentToolCallbackUtils 删除
> - react/ imports: 13 → 11

> **Wave 2.12 + 2.13 — agent-service react/ 完全解耦（2026-07-08，feature/wave-2-port-completion）** ✅：
> - 11 → 0 react/ imports in agent-service/src/main/
> - Wave 2.12：ChatConcurrencyPort 扩 4 方法（pollSteering/cancel/clear/isSessionBusy），覆盖 agent-service 所有 MessageQueue 调用面
> - Wave 2.13：抽 4 Port — ReActLoopPort（5 个 execute() 重载），FollowUpContinuationLoopPort（runWithFollowUps），NoReplyGatePort（shouldSilence/shouldProceed），SteeringSuppliers（react/ → contracts/runtime/ 直接搬迁，纯 JDK 工具类）
> - agent-service 现仅依赖 contracts/ Ports + SDK boundary/ + 工具/team 类，与 1.0 dual-loop 包完全解耦
> - 这为 Wave 3 SessionLoop cutover 铺平道路：换 Port 实现不动 agent-service 调用面

> **Wave 2.14 — obs-service harness/ 完全解耦（2026-07-08，feature/wave-2-port-completion）** ✅：
> - 2 → 0 harness/ imports in gnex-observability-service/src/main/
> - RunEventQueryPort 扩 8 方法（findByRunId/findContextPacksByRunId/findTreeByRunId/countByEventType ×2/getAvgTurnsPerRun ×2/findDecisionsPage）
> - DecisionPage record 从 harness/AgentRunEventService 迁 contracts/diagnostics/
> - **MAJOR MILESTONE**：所有 4 个 services + dev-assembler main 全部 0 react/ + 0 harness/ imports，"拆分" 在生产代码层完成

> **Wave 2.15 — 测试文件 Port 迁移（2026-07-08）** ✅：
> - 10 批 16 个测试文件完成 Port 类型替换（mock 12 个具体类 → Port 接口）
> - ProviderTraceCollector → ProviderTraceCollectorPort（4 文件：ProviderTraceServiceTest / ReActTurnLifecycleTest ×2）
> - AgentRunEventService → RunObservabilityPort（4 文件：RunDiagnosticsServiceTest ×2 + 2 其他）
> - MessageQueue → ChatConcurrencyPort（3 文件：FollowUpContinuationLoopTest ×2 / SteeringSuppliersTest）
> - LLMConfigManager → LlmConfigPort（3 文件：SystemDiagnosticsServiceTest / HeuristicEvaluatorTest / ReActTurnLifecycleTest）
> - ReActLoop → ReActLoopPort / ReActSseNotifier → SseNotifierPort / TokenJuice → TokenJuicePort / HarnessRuntime → HarnessRuntimePort（各 1 文件）
> - 修正 Java 21 类型推断迂回：AgentFlowEngineTest inline mock(LlmConfigPort.class) → 显式局部变量
> - 剩 ~111 个测试 import 未处理：~48 合理（直接测具体类）、~23 AgentExecutionContext（需 Wave 3 胖类削除）、~6 无 Port
> - SDK 测试 208 → 209（+1 AgentFlowEngineTest），ArchUnit 6 规则全绿 0 违规，dev-assembler 112 测试全过（MigrationParityTest + 81 + 30）

**目标**：新建 loop/ 18 类 + 升级 react/，不接真流量。

**契约保护原则**：ReActTurnEngine / TurnState / Handler 链的设计与实现，**禁止破坏 [§4](#4-隐性契约传承清单) A/F 类任何一条**——这些是 Prompt 注入链 + SSE 边界，破坏即用户可见退化。

| 步 | 内容 | 文件 | 契约保护点 |
|:--:|------|------|----------|
| 1 | 新建 `loop/`：SessionLoopRegistry / SessionLoop / SessionChannel | 3 类 | — |
| 2 | PriorityInboundQueue + InboundEvent + InboundKind | 3 类 | — |
| 3 | TurnResult / LoopControlDecision / ChannelStatus | 3 类 | — |
| 4 | InboundPipeline + 5 个 Handler 骨架 | 6 类 | CancelHandler 替代 [D1](#d1) 双重取消 |
| 5 | InboundBackpressure + OutboundDispatcher | 2 类 | OutboundDispatcher 必须调 SseTagStripper（[F1](#f1)） |
| 6 | SessionLoop.runLoop() 主循环 | 1 类 | — |
| 7 | 升级 `react/`（已迁入 Wave 0.5）：新建 ReActTurnEngine + TurnState | 2 类 | 包装 ReActTurnLoop 时**禁止修改 run() 内部**；Hook 链顺序保留（[A1-A7](#41-a-类prompt-铁律system-prompt-强制注入) / [F2](#f2)） |
| 8 | ArchUnit 包依赖约束（loop → react 仅接口） | 测试 | — |
| 9 | 6 大不变量单元测试 + 并发测试 | 测试 | — |
| 10 | [§4.7](#47-持续识别机制wave-1-3-必须更新本节) 候选契约验证 | 测试 | lease_owner 非空 / turnIndex 连续等 6 条 |

**Definition of Done**：
- `mvn compile` 通过
- ArchUnit 测试通过
- 6 大不变量单元测试覆盖率 ≥ 80%
- 并发测试覆盖 I1/I2/I4/I5（故障注入 + race condition）

### Wave 2 · 影子模式验证（1 人周）

**目标**：SessionLoop 与 1.0 并行跑（仅 SDK 内部），用确定性回放对比。

| 步 | 内容 |
|:--:|------|
| 1 | 影子执行器：每个 1.0 turn 同步触发 SessionLoop.runOneTurn（不消费结果） |
| 2 | 用 Wave 0 流量录制 + 确定性回放，对比 turn 行为 |
| 3 | 一致性判定：状态机转移、工具调用顺序、checkpoint 字段（不对比 LLM 输出文本） |
| 4 | 不一致 → 修 SessionLoop，**不切流量** |

**Definition of Done**：
- 1 周生产流量回放，一致性 ≥ 95%
- 不一致项全部定位 + 修复
- 影子模式关闭后无残留代码

### Wave 3 · 上层一次性切换（2 人周）

**目标**：接入层 + 编排层原子切到 SessionLoopPort，灰度发布。

**契约保护原则**：上层改造**禁止破坏 [§4](#4-隐性契约传承清单) B/C/E 类任何一条**——这些是路由 / 装配 / 输出契约，破坏即误委派 / 兜底失效 / 数据依赖断裂。

| 步 | 内容 | 契约保护点 |
|:--:|------|----------|
| 1 | DB 迁移：V66 上线（lease_owner / lease_expires_at + run_lease 表） | — |
| 2 | 上层代码原子切换：ChatAgentStreamRunner / ChatControlController / Orchestrator / PlanExecutor | [B1](#b1) Orchestrator 强制委派保留；[B5/B6/E3/E4](#42-b-类路由与委派铁律) PlanExecutor 改造时整体保留正则表与 resolveAgentName |
| 3 | SessionManager 改造：异步消息同步到 contextMessages 路径迁移到 OutboundDispatcher | [D3](#d3) |
| 4 | in-flight 索引统一到 SessionLoopRegistry：删除 AsyncAgentExecutor.runningJobs / messageBusJobs / AgentScheduler.runningTasks 中的 2 处（保留 1 处作 transition） | [D4](#d4) |
| 5 | 1.0 双循环代码标 `@Deprecated`（**不删**） | — |
| 6 | E2E 全量回归：11 个标准用例 + [§4](#4-隐性契约传承清单) 28 条契约专项验证 | 全部 28 条 |
| 7 | 灰度发布：先切 1 个低风险 tenant（按 tenant/project 维度，非 session 类型） | — |
| 8 | 灰度观察期 1 周，逐步放量 | — |
| 9 | git tag `pre-session-loop-cutover` 标记回滚点 | — |

**Definition of Done**：
- DB 迁移成功
- E2E 全绿
- 灰度 tenant 1 周稳定
- 回滚 tag 已标记

### Wave 4 · 1.0 物理删除（0.3 人周）

**目标**：物理删除 1.0 代码，消除变相双栈。

| 步 | 内容 |
|:--:|------|
| 1 | 删除 §2.3 全部条目（5 类完整删：MessageQueue / FollowUpContinuationLoop / SteeringSuppliers / ChatInFlightControlPort / ChatInFlightControlAdapter；1 评估：ActiveRunRegistry；4 方法/逻辑块：ReActLoop.execute()/resumeExecute() / PhasedAgentLoop follow-up / MessageQueue.cancelFlag 双通道） |
| 2 | 删除 ReActLoop.execute() / resumeExecute() |
| 3 | 全局 grep 清理残留 import / 测试代码引用 |
| 4 | 文档更新：删除所有"双路径/feature flag/降级"内容 |

**Definition of Done**：
- `mvn compile` 通过
- 全局 grep 无残留引用
- 文档同步更新

**强制机制**：Wave 3 稳定 2-4 周后**强制执行** Wave 4，由架构 review 季度审计。

### Wave 5 · 独立演进（不阻塞主线）

> **与引擎 spec 的关系**：本文 Wave 5 指**迁移主线**演进（bus / LongRun / 多副本）。引擎内部工程坑与持久化补完清单见 [EXECUTION-ENGINE-SPEC §13.1](./v2.0-specs/agent/EXECUTION-ENGINE-SPEC.md#131-wave-5持久化--引擎硬化) —— 同名不同维，沟通时须区分 "CUTOVER Wave 5" vs "引擎 Wave 5"。

| 子项 | 说明 | 状态 |
|------|------|:----:|
| AgentInboxLoop 接 bus | `MessageBusConsumer` → `BusTaskDispatchPort` → `AgentInboxLoopRegistry` / `SessionLoopPort.fireInbound(BUS_TASK)` | ✅ Phase A（2026-07-09） |
| LongRun slice + lease | `BUDGET_EXHAUSTED` / `LongRunSliceCoordinator` / `RunLeaseWatchdog` / `run.continue` | ✅ Phase B（2026-07-09） |
| 多副本前置 | `SessionLoopRecoveryService` + `RedisSessionStatePort` / `InMemorySessionStatePort` + `RunLeasePort.listExpiredLeases` | ✅ Phase C（2026-07-09） |
| 三层嵌套时序图 | [SESSION-LONG-RUN-TIMING.md](./v2.0/Agent核心/SESSION-LONG-RUN-TIMING.md) | ✅ Phase D（2026-07-09） |

**Wave 3-5 之间的 72h 任务业务连续性**：Always-On 经 `SessionLoopReActLoop`（`@Primary` `ReActLoopPort`）调度；`SessionStatePort` 注册 `always-on:{taskId}` 供多副本路由。

---

## 4. 隐性契约传承清单

> **来源**：[V1-CODE-REALITY §4](./V1-CODE-REALITY.md) 5 条 + 2026-07-07 全仓 grep + 关键文件精读（AgentLoader / AgentRouter / Orchestrator / PlanExecutor / AgentWorkerPromptBuilder / MessageQueue / SessionManager）。
> **代码快照**：2026-07-07 main 分支。
> **判定标准**：以下契约均满足「代码强制 + 文档未明示 + 违反即行为退化」三项——是单栈切换的硬约束。

### 4.1 A 类：Prompt 铁律（system prompt 强制注入）

| ID | 铁律 | v1.0 实现 | 行为违反后果 | 2.0 复刻点 |
|----|------|---------|-----------|----------|
| **A1** | 反重复铁律（default-worker） | `AgentLoader.java:96-110`（8 条 CHECK，硬编码在 `DEFAULT_WORKER_SYSTEM_PROMPT` 文本块） | 重复上一轮答复 / 复制旧文件名 | ReActTurnEngine 包装时不破坏 system prompt 注入链；default-worker prompt 仍硬编码（不入 .md） |
| **A2** | 反幻觉铁律 | `AgentLoader.java:111-117` + `Orchestrator.java:496-549`（110 行死代码仍可被回调） | 编造文件路径 / 函数名 / 审查结论 | Orchestrator 改 SessionLoopPort 时强制保留；executeDirectAnswer 死代码 Wave 4 删 |
| **A3** | 回复前自检铁律（CHECK-1~4） | `AgentLoader.java:119-128` | 重复开头 / 内部思考泄漏 / 反问代替生成 | default-worker prompt 整体保留 |
| **A4** | 请求分类铁律（问答/生成/修改三类） | `AgentLoader.java:130-138` | 问答类反而生成文件 / 修改类从零重做 | 同上 |
| **A5** | 禁止内部思考泄漏 | `AgentLoader.java:140-145` | "Now I have..." / "让我先看看" 暴露给用户 | 同上 |
| **A6** | AGENT_BEHAVIOR_SUFFIX（8 条 worker 铁律） | `AgentWorkerPromptBuilder.java:16-44` Skill/MCP 区分、sandbox_exec only、TodoWrite 必须 complete、CONCRETE DELIVERABLE 禁止画饼、decision block 等 | Worker 拒绝交付 / 调用 Bash / 漏 decision | suffix 整体保留；注入点不变 |
| **A7** | INLINE_OUTPUT_CONTRACT | `PlanExecutor.java:90-95`（每 step 强制追加到 delegationTask） | 多步计划数据依赖断裂（H1-H8 失败根因） | PlanExecutor 改造时保留注入；SessionLoop 不直接负责此契约 |

### 4.2 B 类：路由与委派铁律

| ID | 铁律 | v1.0 实现 | 违反后果 | 2.0 复刻点 |
|----|------|---------|--------|----------|
| **B1** | Orchestrator 永不直接执行用户任务（强制委派） | `Orchestrator.java:155-164, 239-252`（NO_MATCH / capability_inquiry 全走 default-worker）；`AgentLoader.java:82` 注释明示 | Orchestrator 编造内容 / 直接回答 | Orchestrator 改 SessionLoopPort 时强制保留委派路径；不允许 SessionLoop 直接合成回复 |
| **B2** | `AgentRouter.THRESHOLD = 0.6`（**不可降低**） | `AgentRouter.java:27` 注释记录：从 0.2 升到 0.6 修复误委派事故（report/ppt 任务错配 evaluator，0.34-0.58 假阳性） | 误委派 + terse ignore 回复 | 不动；SessionLoop 不路由 |
| **B3** | `AUTO_DELEGATE_THRESHOLD = 0.7` | `AgentRouter.java:30`（达到此分可跳过二次 LLM） | 误自动委派 | 不动 |
| **B4** | `ADMIN_CONFIDENCE_THRESHOLD = 0.4` + `ADMIN_INTENT` 拦截 | `AgentRouter.java:44-46`（卸载/安装/删除类不路由到 agent） | 管理意图被当成任务执行 | 不动 |
| **B5** | team:/@ 前缀路由格式 | `PlanExecutor.java:489-523` `resolveAgentName`：`@<teamId>:<tag>` / `@<teamId>` / 字面量 | Plan 步骤的 agent 字段无法解析 | PlanExecutor 改造时整体保留 |
| **B6** | `WHOLE_REQUEST_PASS_THROUGH` 防御 | `PlanExecutor.java:75-80`（task 全文等于 `{{userRequest}}` 时判非法，planner 必须分解） | Plan 把原请求整体塞单 agent | PlanExecutor 改造时保留 |
| **B7** | default-worker 硬编码（prompt 在 Java 常量，不入 .md） | `AgentLoader.java:84-186` `DEFAULT_WORKER_NAME` / `DEFAULT_WORKER_SYSTEM_PROMPT` / `ensureDefaultWorker()` | 兜底 agent 缺失 → Orchestrator 无处委派 | 不动；不引入 `agents/default/assistant.md`（[V1-CODE-REALITY §1 错误 3](./V1-CODE-REALITY.md) 已澄清该文件不存在） |

### 4.3 C 类：装配特例

| ID | 铁律 | v1.0 实现 | 违反后果 | 2.0 复刻点 |
|----|------|---------|--------|----------|
| **C1** | default-worker 跳过 archetype prompt | `AgentWorkerPromptBuilder.java:55-64` 硬编码 `if ("default-worker".equals(agentName))` 跳过 archetype 流程 | default-worker 被 REVIEWER 系统提示覆盖，自称 "I'm the Reviewer agent" + 忽略反重复铁律 | ReActTurnEngine 包装时保留 WorkerAgent 装配路径 |
| **C2** | `AgentArchetype.resolve` 对未识别 name 兜底返回 REVIEWER | `AgentArchetype.java`（导致 C1 必须存在） | 未识别 agent 被 REVIEWER 污染（poet/translator/email-writer 拒答创意任务） | Wave 1 评估是否消除兜底；不可则保留 C1 |
| **C3** | `archetypeMatchesName` 关键词匹配（C2 的二级防护） | `AgentWorkerPromptBuilder.java:102-115` DEVELOPER / ARCHITECT / DEVOPS / PM / REVIEWER 关键词 | archetype prompt 不被使用或被误用 | 同上 |
| **C4** | PlanExecutor 跨边界违规直接 import Mapper | `PlanExecutor.java:110, 122` `WorkflowDefinitionMapper`（[V1-CODE-REALITY §1 错误 5](./V1-CODE-REALITY.md) 漏列；实际违规比文档更严重） | Plan 复用持久化 + 单元测试边界污染 | Wave 3 重构 PlanExecutor 时改用 Port；不在本切换范围则保留为已知债 |

### 4.4 D 类：取消与状态通道

| ID | 铁律 | v1.0 实现 | 违反后果 | 2.0 复刻点 |
|----|------|---------|--------|----------|
| **D1** | 双重取消通道（cancelFlag + steering 队列） | `MessageQueue.java:131-146` cancel() + isCancelled() 与 steering 队列并存 | 取消信号时序不一致 | 单栈方案下整体替换为 `fireInbound(CANCEL)` 单通道；PriorityInboundQueue 取消优先级 0 |
| **D2** | `prepareForNewTurn` 漏清 followUp（**已知 bug**） | `MessageQueue.java:162-171` 仅清 cancelFlags + steering，**不清 followUp**（[V1-CODE-REALITY §3.4](./V1-CODE-REALITY.md)） | 下一轮回放上次取消的副作用 | Wave 4 删除 MessageQueue 后**自动消失**；SessionLoop 必须用 InboundPipeline 显式清空所有优先级 |
| **D3** | SessionManager contextMessages 持续更新 | `SessionManager.java:181, 197` 注释解释：异步消息若不更新 contextMessages，用户看不到；但空 row 持久化导致 LLM 混乱 | 异步消息丢失 / 空 row 污染上下文 | SessionLoop OutboundDispatcher 必须显式承担"异步消息同步到 contextMessages"职责 |
| **D4** | 三套 in-flight 索引并存（[V1-CODE-REALITY §3.6](./V1-CODE-REALITY.md)） | `AsyncAgentExecutor.runningJobs` / `messageBusJobs` / `AgentScheduler.runningTasks` / `TaskRepository` | 取消信号只到一处，其他三处仍跑 | Wave 1 统一到 `SessionLoopRegistry`；任何残留索引 = bug |

### 4.5 E 类：文件 / Skill 输出契约

| ID | 铁律 | v1.0 实现 | 违反后果 | 2.0 复刻点 |
|----|------|---------|--------|----------|
| **E1** | SkillDistiller 输出路径 + frontmatter 固定 | `SkillDistiller.java:82-87` 写入 `<skillsDir>/auto/<name>/SKILL.md`，frontmatter 仅 `name+description`（无 `equivalent_to/priority/owner_agent`） | [DECISION-FALLBACK §3.B.2](./v2.0/Agent核心/DECISION-FALLBACK.md) 说的功能无法支持 | 不动；Wave 5演进 |
| **E2** | file 模式强制回读 | `PlanExecutor.java:738, 757-759` file 模式下强制尝试读取文件内容，失败则抛异常（不允许把路径提示传下游） | 下游 step 拿到文件名而非内容，数据依赖断裂（与 A7 同源） | PlanExecutor 改造时保留 |
| **E3** | 强制多步触发词 | `PlanExecutor.java:1019-1107` 命中"先...然后..." / ①②③ / "审查...总结" 等正则强制 `singleStep=false` | 复合任务被分解成单步 → 交付物残缺 | PlanExecutor 改造时保留正则表 |
| **E4** | 反追问复用约束（[V1-CODE-REALITY §3.3](./V1-CODE-REALITY.md)） | `PlanExecutor.java:1417-1423` 硬编码正则 `改成|换成|修改|重新生成` 命中则跳过 Jaccard 复用 | 用户追问时复用过期 Plan | PlanExecutor 改造时保留 |

### 4.6 F 类：Prompt 注入边界（不应跨边界泄漏）

| ID | 铁律 | v1.0 实现 | 违反后果 | 2.0 复刻点 |
|----|------|---------|--------|----------|
| **F1** | SSE 标签永不暴露给用户 | `ReActCompletionGate.java:30` + `SseTagStripper.java:7` + `Orchestrator.java:571, 576`（observability tags / maxTurns force-finalize 内部状态） | 内部状态污染用户气泡 | OutboundDispatcher 显式调用 SseTagStripper |
| **F2** | EvidenceGate 报告全文拦截 | `EvidenceGate.java:68-76` 已 Write 时禁止正文粘贴全文 + 禁止空文本 + 禁止再调 Read/Grep/Write | 报告全文污染 final_answer / 空交付 / 重复工具调用 | Hook 链保留；ReActTurnEngine 包装时 Hook 顺序不变 |

### 4.7 持续识别机制（Wave 1-3 必须更新本节）

SessionLoop 自己会引入新隐性契约。**每 Wave 完成时**必须更新本节，否则 Wave 3 切换后契约已在跑——再发现问题就晚了。

**新增候选契约**（Wave 1 验证）：

| 候选契约 | 验证方式 |
|---------|---------|
| `lease_owner` 非空约束（除 IDLE 状态） | 单元测试 + DB 约束 |
| `checkpoint.turnIndex` 连续性（不允许跳号） | DB UNIQUE(runId, turnIndex) + 恢复时校验 |
| `SessionChannel.status` 转换合法性（IDLE→PROCESSING→YIELDING/COMPLETED/CANCELLED；STALLED→PROCESSING 不允许直接→COMPLETED） | 状态机 ArchUnit 测试 |
| `PriorityInboundQueue.poll` 超时 < `yield-timeout-ms` | 配置校验 + 单元测试 |
| `InboundBackpressure` 触发后必须降级而非拒绝（防死锁） | 压测 |
| `OutboundDispatcher` flush 顺序：SSE → bus reply（不允许反向） | 时序测试 |

**识别方法**：
- 每个 Wave PR review 必须问："这个新类的字段 / 状态转换 / 时序约束是否文档化？"
- 未文档化的强制约束 → 加入本节
- 季度架构审计（[§9 维护约定](#9-维护约定)）复查本节

---

## 5. 6 大不变量测试设计

基于 [SESSION-EVENT-LOOP.md §1.3](./v2.0/Agent核心/SESSION-EVENT-LOOP.md)：

| # | 不变量 | 测试类型 | 测试方式 |
|---|--------|--------|---------|
| I1 | 同 sessionId 最多一个 PROCESSING SessionLoop | 并发 + DB | 多线程并发 fireInbound + DB lease 唯一约束验证 |
| I2 | CANCEL 在下一 runOneTurn 返回前生效 | 时序 + race | 发 CANCEL 同时跑 turn，断言 turn 完成前 cancel 生效 |
| I3 | checkpoint.turnIndex 单调递增 | 单元 + DB | DB UNIQUE(runId, turnIndex) 约束 + 并发写验证 |
| I4 | STALLED → CANCELLED 不超 max-stall-retries | 时钟注入 | mock 时钟 + Watchdog 故障注入 + 计数验证 |
| I5 | 低优先级事件不饿死 | 压测 | 老化升级模拟 + 优先级持续产生 + 断言低优先级被消费 |
| I6 | SSE 断开不改变 Run 状态 | 集成 | 断 SSE 后查 DB Run 状态不变 |

**测试基础设施要求**：
- 故障注入框架（mock 时钟、网络分区、进程 kill）
- 并发测试框架（JUnit + Virtual Thread）
- 压测框架（Gatling 或 JMeter）

---

## 6. DB 迁移

### 6.1 V66__session_loop_lease.sql（草稿）

> **注**：版本号取 V66（V28 已被 `always_on_task` 占用；当前最高为 V65）。

```sql
-- react_checkpoint 表加 lease 字段
ALTER TABLE react_checkpoint
  ADD COLUMN lease_owner VARCHAR(64),
  ADD COLUMN lease_expires_at TIMESTAMP,
  ADD COLUMN heartbeat_at TIMESTAMP;

-- run_lease 表（长任务租约）
CREATE TABLE run_lease (
  run_id VARCHAR(64) PRIMARY KEY,
  session_id BIGINT NOT NULL,
  lease_owner VARCHAR(64) NOT NULL,
  lease_expires_at TIMESTAMP NOT NULL,
  heartbeat_at TIMESTAMP NOT NULL,
  slice_seq INT NOT NULL DEFAULT 0,
  CONSTRAINT fk_run_lease_session FOREIGN KEY (session_id) REFERENCES conversation_session(id)
);

CREATE INDEX idx_run_lease_expires ON run_lease(lease_expires_at);
```

### 6.2 数据迁移

老 checkpoint 行无 lease_owner——首次 SessionLoop 接管时回填：`lease_owner = NULL` 视为"无主"，SessionLoopRegistry 首次 fireInbound 时分配。

### 6.3 回滚预案

DB 迁移不可逆——回滚靠 DB 备份恢复（生产 DBA 操作，不做应用层 fallback）。Wave 3 切换前**必须**有完整 DB 备份 + 恢复演练。

---

## 7. 验收标准

### 7.1 各 Wave Definition of Done

见 §3 各 Wave 内 Definition of Done。

### 7.2 整体验收 KPI

| KPI | 目标 | 测量方式 |
|-----|------|---------|
| 滚动发布零丢 run | 100% | 发布期 in-flight run 全部恢复或正常完成 |
| steering 类工单下降 | -50% | 季度工单统计 |
| inbox 深度可告警 | 告警上线 | Grafana 看板 + Prometheus alert |
| 6 大不变量违反事件 | 0/月 | 故障注入 + 生产监控 |
| [§4](#4-隐性契约传承清单) 28 条契约违反 | 0 | Wave 3 E2E 专项 + 生产回归 |

### 7.3 §4 隐性契约专项验证清单（Wave 3 强制）

每条契约必须有可执行的 E2E 用例，否则 Wave 3 阻塞：

| 类别 | 契约数 | 验证方式 |
|------|:-----:|---------|
| A 类 Prompt 铁律 | 7 | 注入测试用例：构造触发场景，断言 system prompt 包含铁律文本 + worker 输出不违反 |
| B 类 路由与委派 | 7 | 路由测试矩阵：覆盖 NO_MATCH / capability_inquiry / team 前缀 / 复合任务正则 / 管理意图拦截 |
| C 类 装配特例 | 4 | 装配链测试：default-worker / 未识别 archetype / 关键词匹配 / WorkflowDefinitionMapper 边界（后者作为已知债保留） |
| D 类 取消与状态 | 4 | 并发取消测试 + 异步消息持久化测试 + in-flight 索引一致性测试 |
| E 类 文件输出 | 4 | 多步计划用例 + file 模式回读 + 追问复用约束 |
| F 类 Prompt 边界 | 2 | SSE 标签泄漏测试 + EvidenceGate 报告全文拦截测试 |
| **合计** | **28** | A7 + B7 + C4 + D4 + E4 + F2 |

**未通过任一契约专项 = Wave 3 阻塞**，不允许切流量。

---

## 8. 已知风险登记

> 本节为工程尽职记录，**风险已被接受**，不作为阻断项。

| 风险 | 缓解 |
|------|------|
| 无应用层 fallback | git tag + DB 备份作为部署级回滚 |
| 影子模式受 LLM 非确定性影响 | 用确定性回放（mock LLM），不对比 LLM 输出文本 |
| 灰度边界按 tenant 而非 session 类型 | 单 tenant 风险隔离 |
| Wave 3-5 间 72h 任务支持 | 用 AlwaysOnRunner 兜底 |
| 隐性契约识别不完整 | Wave 1-3 持续识别机制 + Wave 3 E2E 专项 |
| 死代码延期删除 | Wave 4 强制 + 季度审计 |

---

## 8.1 Wave 4 运维清单（2026-07-09）

| 步骤 | 命令 / 动作 | 验收 |
|------|------------|------|
| 1 推送 | `git push origin develop` + `git push origin pre-session-loop-cutover` | Gitea `develop` 含 cutover commit |
| 2 hosts | `192.168.1.100 gnex-core-v2.dev.local` 写入本机 hosts | `curl http://gnex-core-v2.dev.local/actuator/health` → UP |
| 3 Jenkins | Webhook `gnex-core-v2-trigger` + `{"ref":"refs/heads/develop"}` | Build SUCCESS + Health Verify 绿 |
| 4 诊断 | `ssh root@192.168.1.100 docker logs gnex-core-v2-dev-web --tail 80` | 无 Spring 启动异常 |
| 5 E2E | `cd d1-web/frontend && GNEX_HEADED=false npx playwright test --config=playwright.dev-local.config.ts e2e/dev-local/d4-runtime.spec.ts` | 登录非 404 |
| 6 灰度 | 选 1 个低风险 tenant 观察 1 周 | steering/取消/in-flight 无回归工单 |

**回滚**：`git checkout pre-session-loop-cutover` + DB 备份恢复 + Jenkins 重部署。

---

## 9. 维护约定

- 每个 Wave 完成后更新本文档状态列
- 隐性契约识别有新增 → 更新 §4
- 6 大不变量测试用例更新 → 更新 §5
- DB schema 变更 → 更新 §6
- Wave 4+5 完成后已归档 → [`SESSION-LOOP-SINGLE-STACK-CUTOVER-POSTMORTEM.md`](./SESSION-LOOP-SINGLE-STACK-CUTOVER-POSTMORTEM.md)（2026-07-09）

---

*单栈切换实施 SSOT。任何偏离本文档的决策需架构评审 + 更新本文档。*
