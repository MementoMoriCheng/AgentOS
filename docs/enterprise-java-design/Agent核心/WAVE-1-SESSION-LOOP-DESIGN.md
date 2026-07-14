# Wave 1 — SessionLoop 单栈调度内核设计

**版本**：v1（2026-07-07）
**分支**：`feature/wave-1-session-loop`（9 commit，待 review）
**前置**：[Wave 0.5 SDK 拆分](./SDK-SPLIT-WAVE-0.5-RECON.md) ✅
**参照**：[SESSION-LOOP-SINGLE-STACK-CUTOVER.md](../../SESSION-LOOP-SINGLE-STACK-CUTOVER.md) §3 Wave 1

---

## 概览

Wave 1 落地 SessionLoop 单栈调度内核 + Port 收敛第一波，是 v2.0 单栈替代 1.0 双循环（PhasedAgentLoop / FollowUpContinuationLoop / SteeringSuppliers）的核心阶段。

| Phase | 内容 | 实际工作量 | 计划估 | 状态 |
|-------|------|-----------|-------|:----:|
| 1 | context/ 拆分 + ContextTrimmingPort 抽象 | 0.5 人周 | 0.5-0.8 | ✅ |
| 2 | loop/ 19 类内核（5 切片 S1-S5）| 1.2 人周 | 1-1.2 | ✅ |
| 3 | ReActTurnEngine facade | 0.5 人周 | 0.5-0.7 | ✅ |
| 4 | 371 → ~120 violation 收敛 | 0.4 人周 | 0.8-1 | ⚠ 部分 |
| 5 | DoD + 文档同步 | 0.3 人周 | 0.4-0.5 | ✅ |
| **合计** | | **2.9 人周** | **3.2-4.2** | |

实际比计划估低 10%，主要节省来自 Phase 4 部分工作推 Wave 1.5。

---

## 1. Phase 1 — context/ 拆分 + ContextTrimmingPort

### 1.1 阻断背景（RECON §9）

Wave 0.5 拆 context/ 6 类时阻断：

```
PreReasoningHook (runtime/, 将归 react/)
    ↓ 方法签名硬编码
ContextCompactor (迁 context/)
    ↓ 使用
AgentExecutionContext (runtime/, 将归 harness/)
```

形成 react → context → harness 的反向依赖链。

### 1.2 决策（用户在 plan 阶段确认）

**方案 = X+Y 组合**：
- X = 抽 `ContextTrimmingPort` 到 contracts/runtime/
- Y = 改 PreReasoningHook 签名，弱化 hook 对具体类型的依赖

落地区别于纯 X：方案 X 单独抽 Port 还不够，因为 PreReasoningHook 的方法签名硬编码 ContextCompactor 类型——只要签名不变，context/ 一动，PreReasoningHook 就编译错。

### 1.3 落地

**contracts/runtime/ 新增**：
- `ContextTrimmingPort`（10 methods，含 read-only accessors `getContextWindow`/`getCompactThreshold` + 8 个核心 compaction 方法）
- `CompactSummary` record（从 ContextCompactor 嵌套 record 抽出）

**SDK context/ 子包（6 类）**：
- `ContextCompactor` implements ContextTrimmingPort
- `ContextPack` / `CompressionTemplate` / `CompressionValidator` / `ConversationSummarizer`（从 runtime/ 迁）
- `ContextPackRecorder`（从 react/ 迁——按功能归 context/）

**Hook 签名重塑**：
- `PreReasoningHook.beforeLlm`：第三参 `ContextCompactor` → `ContextTrimmingPort`
- 4 个 impl 同步：ContextTrimmingHook / ContextPackRecorder / MemoryRecallHook / DiscoveryPreReasoningHook
- `TokenJuice.applyToMessages` + `TurnSnipEngine.snipIfNeeded` 接 Port

### 1.4 ArchUnit 影响

- 规则 3 启用：`context/ 不依赖 react/ 或 harness/`
- frozen baseline：10 violations（旧 frozen entry 因签名变更过期，重冻）
- react→harness 冻结库也重冻（371 → 372）

---

## 2. Phase 2 — loop/ 19 类内核

### 2.1 5 个切片

按风险递增分 5 切片，每切片独立 commit + 测试。

| 切片 | 内容 | 风险 |
|------|------|:----:|
| **S1** | 6 个值对象/枚举（InboundKind / ChannelStatus / InboundEvent / TurnResult / LoopControlDecision / SessionChannel）| 低 |
| **S2** | PriorityInboundQueue（双 tier）+ InboundHandler / InboundPipeline 接口 | 中 |
| **S3** | SessionLoop 主循环状态机 + TurnRunner 接口 | **高** |
| **S4** | 5 个 InboundHandler stub + DefaultInboundPipeline + OutboundDispatcher + InboundBackpressure | 中 |
| **S5** | SessionLoopRegistry + ArchUnit 规则 4 + E2E 冒烟 | 中 |

### 2.2 关键设计决策（locked）

#### 决策 1：每个 turn 由且仅由一个 InboundEvent 触发

**理由**：SessionLoop 永不连续 turn。即使 TurnResult.CONTINUE 也等下个 event。消除 reentrant scheduling 风险，loop 单路径无隐藏工作。

**对比**：1.0 PhasedAgentLoop 允许 turn 内连续 LLM 调用（`while (!finalAnswer)` 循环），引入死锁/堆栈深问题。SessionLoop 强制每 turn 退出 → 重新 poll。

#### 决策 2：Tier-based 双队列（用户确认）

- HIGH tier: INTERRUPT + DELEGATION（总是先耗尽）
- NORMAL tier: USER + TOOL_RESULT
- BACKPRESSURE **不入队**（走外部 callback）

**对比**：方案 2 PriorityBlockingQueue 单队列语义模糊；方案 3 三层无必要。

#### 决策 3：BACKPRESSURE 不入队

走外部回调（InboundBackpressure.onOffer 返回 Optional<InboundEvent>），由 SessionLoop 直接 dispatch 给 pipeline，避免与 user/interrupt 抢 worker。

#### 决策 4：ArchUnit 规则 4 strict（非 frozen）

loop/ 当前 0 依赖 react/ 或 harness/，所以规则 fail-fast 而不是 freeze。Phase 3 引入 ReActTurnEngine 时**故意放在 react/ 而非 loop/**，保持规则 4 strict。

### 2.3 状态机

```
IDLE ──runLoop()──▶ RUNNING ──poll empty──▶ YIELDING ──event arrives──▶ RUNNING
                       │                          │
                       └──── TERMINATE ──────────▶ TERMINATED
```

转换用 CAS（`SessionChannel.transitionTo(expected, next)`），保证线程安全。

### 2.4 决策映射

| LoopControlDecision | 含义 |
|---|---|
| PROCEED | 跑 turn（调 TurnRunner.run），然后回到 YIELDING |
| YIELD | 不跑 turn，直接回到 poll |
| TERMINATE | 终止 loop（CAS terminated = true，channel status = TERMINATED）|

---

## 3. Phase 3 — ReActTurnEngine facade

### 3.1 偏离 plan：放 react/ 而非 loop/

Plan 原话：「新建 `loop/ReActTurnEngine.java`」。

**实际做法**：放 `react/ReActTurnEngine.java`。

**原因**：TurnRequest 引用 react/ 类型（CompositePreReasoningHook / ContextTrimmingHook / ReActTurnLoop 等）。放 loop/ 会破坏 ArchUnit 规则 4（loop/ 0 依赖 react/）。

**对架构的影响**：依赖方向是 react/ → loop/TurnRunner，符合层级（react/ 高层，loop/ 低层）。规则 4 保持 strict。

### 3.2 ReActTurnLoop.run() 的 20 个参数问题

ReActTurnLoop.run() 签名有 20 个参数（systemPrompt / userInput / toolCallbacks / maxTurns / model / RouteDecision / messages / hooks / etc.），无法从 (SessionChannel, InboundEvent) 推导。

**解决方案**：
- `TurnRequest` record 持有 20 参数
- `TurnRequestResolver` @FunctionalInterface 从 (channel, trigger) → TurnRequest
- `ReActTurnEngine` 注入 `ReActTurnLoop + TurnRequestResolver`，调 resolver → 拿到 TurnRequest → 转 20 个参数 → 调 turnLoop.run() → 翻译 ReActResult

**生产 wiring**：Wave 2 切换 SessionLoop 时落地，把 ReActLoop.execute 的参数装配逻辑搬过来。

### 3.3 翻译规则

| ReActResult | TurnResult |
|---|---|
| null | COMPLETED |
| text 含"已取消" | YIELD |
| text 含"max_turns" | YIELD |
| 其他 | COMPLETED |

tokens 从 ReActResult.totalTokenUsage() 来。

### 3.4 不动承诺

- ✅ 没修改 ReActTurnLoop / ReActTurnLifecycle / ReActLlmInvoker / ReActToolActPhase / ReActToolDispatcher 任何内部代码
- ✅ 没改 ReActLoop 的现有调用点（Wave 2 才切换）
- ✅ F2 hook 链顺序不变（11 个 E2E 测试兜底）

---

## 4. Phase 4 — violation 收敛（部分完成）

### 4.1 已完成

| 子任务 | 内容 | violation 变化 |
|---|---|:---:|
| P4.1 | RouteDecision 迁 contracts/runtime/ | **−41** |
| P4.2 | ReActTurnLifecycle 收窄到 LlmConfigPort | **−5** |

baseline 演化：375 → 334 → **329**

### 4.2 阻塞路径（Wave 1.5 工作）

每个阻塞根因相同：**Port API 太窄，无法承载 react/ 实际用法**。

| Port | 当前 API | react/ 实际需要 | 差距 |
|---|---|---|---|
| `ChatRunContext` | 7 getters | +10 setters/getters（getModelCallEventId / isSingleFileReviewMode / setCompletionEvidence / tryMarkSseRunningEmitted 等）| 大 |
| `RunObservabilityPort` | 2 (mirrorEvent, clearRun) | +7 recordX 方法（recordPhase / recordModelCall / recordToolCall / recordError 等）| 大 |
| `LlmConfigPort` | 14 | +4（createChatModel / getContextWindow / getFallbackModels / auth profile 生命周期）| 中 |

### 4.3 已识别的 5 个未迁移文件

| 文件 | 阻塞方法 | 等待 |
|---|---|---|
| ReActLoop | createChatModel / getContextWindow | LlmConfigPort 扩 API |
| ReActTurnLoop | 透传参数 | ReActCompletionGate.finishWithoutToolCalls 签名升级 |
| ReActModelFallback | createChatModel / getFallbackModels | LlmConfigPort 扩 API |
| ReActLlmInvoker | createChatModel / recordAuthProfileSuccess / rotateAuthProfile | 拆 AuthProfilePort |
| ReActCompletionGate | createChatModel / getContextWindow | LlmConfigPort 扩 API |

---

## 5. Phase 5 — DoD + 测试 + 文档

### 5.1 4/6 不变量测试落地（I1/I2/I4/I5）

`SessionLoopInvariantsTest.java`：

- **I1 单 session 串行**：2 线程并发 runLoop → CAS 保证只有 1 个赢
- **I2 跨 session 隔离**：2 个 SessionChannel 独立运行，互不阻塞
- **I4 Backpressure**：队列水位上行穿越 → BACKPRESSURE event → pipeline YIELD
- **I5 中断传播**：INTERRUPT 入 HIGH tier，下个 poll 抢占 USER，loop 终止

**I3（turn fairness）+ I6（graceful shutdown drain）** 留 Wave 2（接真流量后才能验证）。

### 5.2 文档同步

- ✅ [SESSION-LOOP-SINGLE-STACK-CUTOVER.md](../../SESSION-LOOP-SINGLE-STACK-CUTOVER.md) Wave 1 标完成
- ✅ [SDK-SPLIT-WAVE-0.5-RECON.md](./SDK-SPLIT-WAVE-0.5-RECON.md) §9.4 加 Wave 1 实际解决方案
- ✅ 本文档（WAVE-1-SESSION-LOOP-DESIGN.md）

### 5.3 验收

- SDK 测试 **203/203**（Phase 1 后 109 → +94）
- 全 reactor 编译绿
- ArchUnit 5 规则全绿：
  - boundary → react/harness（strict）
  - memory → react/harness（strict）
  - service → react（strict）
  - react → harness（frozen, 329 baseline）
  - context → react/harness（frozen, 10 baseline）
  - loop → react/harness（**strict, 0 violations**）

---

## 6. Wave 1.5 优先工作

基于 Phase 4 实测发现的 Port API 设计 gap：

1. **扩 ChatRunContext Port** 或拆出新 `AgentRunContextPort`（覆盖 17 个 react/ 实际方法）
2. **扩 RunObservabilityPort** 或拆出新 `RunEventPort`（覆盖 7 个 recordX 方法）
3. **扩 LlmConfigPort** 加 createChatModel / getContextWindow / getFallbackModels
4. **拆 AuthProfilePort** 收 recordAuthProfileSuccess / rotateAuthProfile

**✅ Wave 1.5 已完成（2026-07-07）**：4 项全部落地，外加 StrictnessLevel 迁 contracts/。实际收益 329 → 178 violations（-46%）。详见 [WAVE-1-PORT-EXPANSION.md](./WAVE-1.5-PORT-EXPANSION.md)。

---

## 7. Wave 2 前置条件

进入 Wave 2（已完成 ✅）：

- [x] Wave 1 merge 到 develop
- [x] Wave 1.5 启动决策（是否先收敛 Port 再上影子）
- [x] ReActTurnEngine 的 TurnRequestResolver 生产实现
- [x] ReActLoop → SessionLoop 调用切换设计（保留旧入口还是直接替换）

---

*Wave 1 设计稿 v1，2026-07-07，基于 feature/wave-1-session-loop 9 commit + 4 次用户决策（X+Y 方案 / 分阶段收敛 / 全迁 6 类 / Tier-based 双队列）。*
