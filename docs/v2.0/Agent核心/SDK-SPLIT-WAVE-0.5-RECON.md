# Wave 0.5 SDK 拆分侦察报告

> **状态**：✅ 已完成（**v3 2026-07-07**：react/+harness/ 已合，108 tests pass，ArchUnit 4 规则冻结）
> **关联**：[SESSION-LOOP-SINGLE-STACK-CUTOVER.md §2.1 / §3 Wave 0.5](./SESSION-LOOP-SINGLE-STACK-CUTOVER.md)
> **代码快照**：2026-07-07 develop 分支
> **目的**：把 §2.1 表格的"~25/~10/~15"模糊估算替换为精算类清单，并审计 Spring/reflection 风险，作为 Wave 0.5动手前的最后一道闸。

> **⚠️ v2 修订（2026-07-07）**：实测发现 context/ 拆分遇到设计层阻断（详见 §2.2 与 §9 阻断记录）。**Wave 0.5 范围调整为只拆 react/ + harness/**。context/ 留 runtime/ 暂不动，等 Wave 1 设计 SessionLoop 时一并解决 hook 链边界。
>
> **✅ v3 完成度（2026-07-07）**：react/ 54 类 + harness/ 36 类机械拆分完成；4 条 ArchUnit FreezingArchRule 冻结基线（react→harness 371 violations 入库）；SDK 108/108 tests pass；详见 §8.1 实测工作量与 §8.2 ArchUnit 结果。

---

## 1. 现状摸底

### 1.1 SDK 子包分布（拆分前）

| 子包 | 文件数 | 拆分动作 |
|------|:----:|------|
| `boundary/` | 22 | **不动** |
| `memory/` | 16 | **不动** |
| `service/` | 9 | **不动** |
| `config/` | 1 | **不动** |
| `output/` | 1 | **不动**（CUTOVER 未列入拆分范围） |
| `tools/` | 3 | **不动**（同上） |
| `workspace/` | 12 | **不动**（同上） |
| `runtime/` | **105** | **本 Wave 拆分对象** → 拆到 react/ harness/ context/ |
| `common/sse/` `common/trace/` `common/observing/` | 6 | **不动**（CUTOVER §2.2 列为越界下放，但不在 Wave 0.5 范围） |

### 1.2 runtime/ 105 类精算分组

| 目标子包 | 估算 | 精算 | 差异原因 |
|---------|:----:|:----:|---------|
| `react/` | ~25 | **~54** | 原 §2.1 严重低估——Hook 链 11 类 + Tool 调用 7 类 + Turn/Loop 8 类都该归此处 |
| `harness/` | ~10 | **~36** | 原 §2.1 漏算——LLM 配置/限流/熔断、Token 计量、Routing、Provider trace 都属基础设施 |
| `context/` | ~15 | **~10** | 原 §2.1 高估——`memory/` 已独立，且 Hook 类按 hook 链归 react/ |
| 越界保留 runtime/ | — | **~9** | CUTOVER §2.2 越界文件（Wave 0.5 不动） |

**净影响**：react/ harness/ 比 §2.1 估算翻倍。Wave 0.5 工作量从"1-1.5 人周"可能上调到 **1.5-2 人周**（git mv + import 重构数量增加）。

---

## 2. 精算类清单

### 2.1 react/（约 54 类）— ReAct 推理循环 + Hook 链 + Tool 调用 + Turn/Loop 控制

#### 2.1.1 ReAct 前缀（19）

```
ReActChatOptionsFactory       ReActCheckpointService       ReActCheckpointSnapshot
ReActCompletionGate           ReActContextHelpers          ReActLlmInvoker
ReActLoop                     ReActLoopConstants           ReActMessageCodec
ReActMessagePreview           ReActModelFallback           ReActSseNotifier *
ReActToolActPhase             ReActToolChecks              ReActToolDispatcher
ReActTurnLifecycle            ReActTurnLoop                ReActTurnPreamble
ReActTokenUsage
```
> *ReActSseNotifier 是 §2.2 越界下放目标（→ agent-service/infra/sse/），Wave 0.5 期间暂入 react/，下放时再迁出。

#### 2.1.2 Hook 链（16）— 基类 + Composite + 实现

```
PreReasoningHook (interface)  CompositePreReasoningHook    CompositePostReasoningHook
CompositePostTurnHook         ContextTrimmingHook          DiscoveryPreReasoningHook
MemoryRecallHook †            AutoMemoryHook †             DecisionRecorder
TurnRecorder                  SessionMemoryRecorder †      ContextPackRecorder †
EvidenceGate                  NoReplyGate                  PromptThreatScanner
AnomalyDetector
```
> † 标记的 4 个类有争议：实现 Hook 接口但功能属 context/。本报告建议**按 hook 链归 react/**（hook 注册顺序是隐性契约，混放难追踪）。架构评审可改判。

#### 2.1.3 Tool 调用相关（7）

```
ToolCallFormatGuard           ToolCallSchemaValidator      ToolPairIntegrity
ToolResultOffloader           AgentToolCallbackUtils       CoordinatorToolPolicy
PhaseToolWhitelist
```

#### 2.1.4 Turn / Loop 控制（12）

```
TurnFinalizer                 TurnSnipEngine               TurnRecorder (PostReasoningHook)
PhasedAgentLoop               FollowUpContinuationLoop *   SteeringSuppliers *
MessageQueue *                ActiveRunRegistry (评估) *   StagnationDetector
TodoSessionTracker            DecisionAttribution          ProceduralSkillInjector
ProjectConstraintRenderer
```
> *Wave 4 删除目标，Wave 0.5 原样迁入 react/。`ProjectConstraintRenderer` 功能偏 prompt 构造，可考虑改归 boundary/——评审决定。

### 2.2 context/（约 10 类）— 上下文 / 压缩 / 摘要 — ⚠️ **本 Wave 不拆**

```
ContextCompactor              ContextPack                  ContextPackRecorder †
CompressionTemplate           CompressionValidator         CompactionBatch (在 memory/，不动)
ConversationSummarizer (interface)
```

> **🚫 v2 阻断记录（2026-07-07 实测）**：尝试把这 6 类（除 CompactionBatch）迁到 context/ 后，触发 4 处编译错误，根因是设计层循环依赖：
>
> 1. `PreReasoningHook.beforeLlm(...)` 方法签名硬编码 `ContextCompactor` 类型——hook 链（将归 react/）强依赖 context/
> 2. `ContextCompactor` 用 `AgentExecutionContext`（将归 harness/）——context/ 反向依赖 harness/
> 3. `ContextPackRecorder implements PreReasoningHook` 但功能属 context/——context/ 反向依赖 react/
>
> **违反 RECON §5 ArchUnit 草案规则 2 + 3**。这是设计问题，机械重构无法解决——需要先做 Port 抽象或调整 hook 链 API。
>
> **决策**：context/ 拆分**延后到 Wave 1**（届时 SessionLoop 设计会重塑 hook 链 + context 边界）。本 Wave 0.5 这 6 类**全部留 runtime/ 暂不动**。
>
> † `ContextPackRecorder` 归属争议随 context/ 拆分一并延后。

### 2.3 harness/（约 36 类）— 基础设施 + 编排 + 资源管理

#### 2.3.1 Harness / Agent 装配（10）

```
HarnessRuntime                AgentRuntime                 AgentRunEventService
WorkerAgent (record)          LoadedAgent (record)         WorkerTaskBundler
AgentExecutionContext          ReviewTaskPolicy             ScenarioClassifier
LiveSmokeTestProvider
```

#### 2.3.2 LLM / Provider 基础设施（8）

```
LLMConfigManager              LlmCircuitBreaker            LlmRateLimiter
ModelRouter                   ProviderTraceCollector       ProviderTraceProtocol
ProviderTraceService          ConstrainedDecodingLayer
```

#### 2.3.3 Token / Usage 计量（6）

```
UsageTracker                  TokenJuice                   TokenJuiceApplyResult (record)
TokenJuiceRuleLoader          TokenSaver                   RoutingMetrics
```

#### 2.3.4 Routing / Delegation（7）

```
AgentMatch (record)           AgentRouteTrust              AgentRouteTrustChecker
RouteDecision (record)        DelegationCancelRegistry     DelegationDeliverableResolver
RunEventSummary (record)
```

#### 2.3.5 配置 / 环境 / 杂项（5）

```
ConfigAuditor                 EnvironmentContractBuilder   ProactiveTicker
StrictnessLevel (enum)        PhaseType (enum)
```

### 2.4 越界保留 runtime/（约 9 类）— Wave 0.5 不动

CUTOVER §2.2 列的越界下放目标（→ agent-service/*），不在 Wave 0.5 范围：

```
AuthProfileManager            ChatRunContextPortAdapter    WebConfirmationHandler
WebQuestionHandler            CancelableQuestionHandler    PendingConfirmation
QuestionAnswerPortAdapter     DelegationControlPortAdapter ReActSseNotifier (若不归 react/)
```

**建议**：Wave 0.5 期间这些类**保留在 runtime/ 原位**，避免和 §2.2 越界下放工作交织。下放工作可独立做或 Wave 4 一起做。

---

## 3. Spring 注入审计 — 零阻断

| 检查项 | 结果 |
|------|------|
| `@SpringBootApplication` 位置 | `gnex-dev-assembler/.../GnexApplication.java:23` |
| 默认扫描包 | `com.gnex.*`（无显式 scanBasePackages） |
| SDK 新包路径 | 仍在 `com.gnex.agent.{react,harness,context}.*` → **自动被扫** |
| 显式 `@ComponentScan(basePackages=...)` | 仅 `gnex-bus-service` 用 `scanBasePackages = "com.gnex.bus"`，不依赖 SDK 包路径 |
| `@EntityScan` / `@EnableJpaRepositories` | 无 |
| SDK 内 `@Component/@Service/@Configuration` | 大量（AgentRuntime / AgentRunEventService / GnexMemoryService 等），依赖默认扫描 |

**结论**：拆包后 Spring 注入**零阻断**。

---

## 4. 反射 / 字符串引用审计 — 零阻断

| 检查项 | 结果 |
|------|------|
| `Class.forName("com.gnex.agent.runtime.X")` | **零命中**（全仓） |
| 硬编码全限定类名字符串 `"com.gnex.agent.runtime."` | **零命中**（全仓） |
| `@JsonTypeInfo` / `@JsonSubTypes` 多态类型 | **零命中**（SDK 内） |
| `META-INF/spring.factories` | **不存在** |
| `META-INF/services/*` | **不存在** |
| `application.yml` 硬编码 SDK 类名 | **零命中**（`gnex-dev-assembler/src/main/resources/application.yml`） |

**结论**：反射层面**零阻断**。

---

## 5. ArchUnit 规则草案

```java
@AnalyzeClasses(packages = "com.gnex.agent")
class AgentSdkArchitectureTest {

    // 1. 不动子包不依赖可动子包
    @ArchTest
    static final ArchRule boundary_not_depend_on_runtime_split =
        noClasses().that().resideInAPackage("..boundary..")
            .should().dependOnClassesThat().resideInAnyPackage("..react..", "..harness..", "..context..");

    // 2. react/ 不依赖 harness/ 或 context/
    @ArchTest
    static final ArchRule react_not_depend_on_harness_or_context =
        noClasses().that().resideInAPackage("..react..")
            .should().dependOnClassesThat().resideInAnyPackage("..harness..", "..context..");

    // 3. context/ 不依赖 react/ 或 harness/
    @ArchTest
    static final ArchRule context_not_depend_on_react_or_harness =
        noClasses().that().resideInAPackage("..context..")
            .should().dependOnClassesThat().resideInAnyPackage("..react..", "..harness..");

    // 4. loop/ 仅通过接口依赖 react/（Wave 1 启用，Wave 0.5 占位）
    // @ArchTest
    // static final ArchRule loop_depends_on_react_only_via_interfaces = ...;

    // 5. 所有可动子包都可依赖 boundary/memory/service/config
    //（默认允许，无需规则）
}
```

**已知违规风险**：
- `react/ReActLoop` 当前依赖 `harness/HarnessRuntime`（待确认）—— 若违反规则 2，需要评审是放行还是引入 Port
- `react/Hook` 实现类访问 `memory/MemoryIndex` —— 不违反（memory 不在限制范围）
- `context/ContextCompactor` 调用 `react/ReActLlmInvoker`（待确认）—— 若违反规则 3，需评审

**Wave 0.5 执行策略**：先跑 ArchUnit 看实际违规清单，再决定规则是收紧（修代码）还是放宽（添 `@SuppressWarnings` 或允许例外）。

---

## 6. Wave 0.5 工作量重估（v2：context/ 不拆后下调）

| 子任务 | v1 重估 | v2 重估 | 说明 |
|--------|:----:|:----:|------|
| git mv 类到目标子包 | 0.5 人周 | **0.4 人周** | react ~54 + harness ~36 = ~90 类（context 不拆） |
| import 重构（sed 批量 + 修编译错误） | 0.3 | **0.4** | 实测：sed 后总有 2-4 处 implicit 引用需手动加 import |
| ArchUnit 规则 + 修违规 | 0.4 | **0.3** | 只跑规则 1+2（不动子包 + react 不依赖 harness）；规则 3 因 context 不拆暂搁置 |
| mvn compile + E2E 回归 | 0.5 | **0.4** | 同 v1 |
| 缓冲（返工） | 0.3 | **0.3** | 实测已踩 1 个坑（context 双向依赖），仍有未知坑 |
| **合计** | **2 人周** | **1.8 人周** | 下调 0.2 |

**建议**：把 [SESSION-LOOP-SINGLE-STACK-CUTOVER.md](./SESSION-LOOP-SINGLE-STACK-CUTOVER.md) §3 Wave 0.5 标题从"1-1.5 人周"改为"1.5-2 人周"。

---

## 7. 待评审决策清单

| # | 决策点 | 选项 A | 选项 B | 本报告倾向 | 状态 |
|:--:|------|------|------|------|:----:|
| 1 | Hook 实现类（Memory/AutoMemory/ContextPackRecorder/SessionMemoryRecorder）归属 | react/（hook 链） | context/（功能） | **react/**（hook 注册顺序是隐性契约） | 🟡 延后到 Wave 1（context 不拆后此项不再迫切） |
| 2 | `ProjectConstraintRenderer` 归属 | react/（turn 内 prompt） | boundary/（prompt 模板） | **react/**（先按 hook 链规则，后续可调） | ☐ 评审 |
| 3 | 越界保留 9 类 Wave 0.5 处理 | 留 runtime/ 原位 | 顺手迁出 | **留原位**（避免和 §2.2 工作交织） | ✅ 采纳 |
| 4 | ArchUnit 规则发现违规时 | 修代码迁 Port | 添允许例外 | **看违规数**（< 3 处修代码；≥ 3 处添例外并加 TODO） | ☐ 待跑 ArchUnit 后定 |
| 5 | `output/` `tools/` `workspace/` 子包 | 不动 | 一并整理 | **不动**（不在 CUTOVER 范围，避免范围蔓延） | ✅ 采纳 |
| 6 | §2.1 表格"~25/~10/~15"是否同步更新 | 改 RECON 数字 | 保留原文 + 加注释指向本报告 | **同步改**（避免数字分裂） | ✅ 采纳（[CUTOVER §2.1](./SESSION-LOOP-SINGLE-STACK-CUTOVER.md) 已用 Wave 列标注，本报告 §1.2 为精算） |
| **🆕 7** | **context/ 拆分如何处理** | **延后 Wave 1**（hook 链重塑时一并解决） | **现在做 Port 抽象**（先抽 ContextCompactorPort） | **延后 Wave 1** | ✅ 采纳（实测阻断） |

---

## 8. 下一步动作（v2 调整后）

1. ✅ ~~架构评审本报告~~ — 决策 #3/#5/#6/#7 已采纳；#1 延后；#2/#4 待执行中定
2. ✅ 开 `feature/wave-0.5-sdk-split` 分支（基于 develop 最新）
3. ✅ **第二轮**：拆 react/（54 类）→ mvn compile 验证（commit `62ad9b8`）
4. ✅ **第三轮**：拆 harness/（36 类）→ mvn compile 验证（commit `e696139`）
5. ✅ ArchUnit 写规则 1+2+4 + 规则 service→react（4 条 FreezingArchRule）（commit `7d2496b`）
6. ✅ `mvn test libs/gnex-agent-sdk` 跑通 108 tests（含 SdkArchitectureTest 4 + 各子包单测）
7. ☐ PR review → 合 develop
8. ☐ 同步更新 [SESSION-LOOP-SINGLE-STACK-CUTOVER.md](./SESSION-LOOP-SINGLE-STACK-CUTOVER.md) §2.1 数字 + Wave 0.5 工作量
9. **延后项**：context/ 拆分 → Wave 1 SessionLoop 设计时统一规划 hook 链 + context 边界

### 8.1 实测工作量（v3 复盘）

| 子任务 | v2 重估 | v3 实际 | 说明 |
|--------|:----:|:----:|------|
| git mv 类到目标子包 | 0.4 | **0.3** | react 54 + harness 36 = 90 类一次性 git mv |
| import 重构 + spurious 清理 | 0.4 | **0.7** | sed 批改 + 3 轮 mvn compile 修 implicit 引用 + 清 contracts/platform-persistence 的伪 import |
| ArchUnit 规则 + 冻结基线 | 0.3 | **0.2** | 4 条规则，371 react→harness violations 冻结 |
| mvn compile + test 回归 | 0.4 | **0.3** | SDK 108/108 pass；dev-assembler 编译通过（develop 上原本就编译失败） |
| 缓冲（返工） | 0.3 | **0.3** | context 阻断 + ArchUnit store 重冻结 + ReActTurnPreambleTest Mockito + 几处 develop 已存在的 typo |
| **合计** | **1.8** | **1.8 人周** | 实测符合 v2 重估 |

### 8.2 ArchUnit 实测结果

| 规则 | 违规数 | 说明 |
|------|:----:|------|
| `boundaryShouldNotDependOnReactOrHarness` | **0** | boundary/ 是干净的叶子包 |
| `memoryShouldNotDependOnReactOrHarness` | **0** | memory/ 是干净的叶子包 |
| `serviceShouldNotDependOnReact` | **0** | service/ 不依赖 react/ |
| `reactShouldNotDependOnHarness` | **371** | 冻结为基线，Wave 1 SessionLoop 重塑时消除 |

371 violations 的根因：ReActLoop / ReActTurnLifecycle / ContextTrimmingHook 等核心 react/ 类
在构造函数和方法签名上直接引用 HarnessRuntime / AgentExecutionContext / TokenJuice /
LLMConfigManager 等 harness/ 类。这是当前 ReAct loop 与 harness 紧耦合的真实状态，
Wave 1 设计 SessionLoop 时通过 Port 抽象解耦。

---

## 9. v2 阻断记录（2026-07-07）

### 9.1 实测过程

1. 在 `feature/wave-0.5-sdk-split` 分支按 §2.2 清单 `git mv` 6 个 context 类
2. sed 批量改 package 声明 + 全仓 import
3. `mvn compile` → 4 处编译错误：
   - `ContextPackRecorder.java:14` 方法签名不匹配 PreReasoningHook
   - `ContextCompactor.java:214` 找不到 AgentExecutionContext
   - `ContextTrimmingHook.java:22,29` 找不到 ConversationSummarizer
   - `ReActLoop.java:176` 找不到符号（ContextCompactor 相关）
4. 手动加 import 后仍剩 4 处编译错误（双向依赖）→ 设计层阻断
5. **`git reset --hard origin/develop` + `git clean -fd`** 完全回滚

### 9.2 根因

```text
PreReasoningHook (runtime/, 将归 react/)
    ↓ 方法签名硬编码
ContextCompactor (迁 context/)
    ↓ 使用
AgentExecutionContext (runtime/, 将归 harness/)
```

形成 react → context → harness 的反向依赖链，与 ArchUnit 草案规则 2 + 3 冲突。

### 9.3 解决方向（留给 Wave 1）

- **方案 X**：抽 `ContextCompactorPort`（在 boundary/），PreReasoningHook + ContextCompactor 都依赖 Port
- **方案 Y**：把 `PreReasoningHook` 重构为不传 ContextCompactor，只传 `List<Message>` + `int turn`，让 hook 内部按需获取 compactor
- **方案 Z**：把 hook 链 + context 一并放 react/（牺牲 context/ 子包的独立性）

Wave 1 设计 SessionLoop 时统一决策，本 Wave 0.5 不涉及。

### 9.4 ✅ Wave 1 实际解决方案（2026-07-07）

采用 **方案 X+Y 组合**（用户在 Wave 1 plan 阶段确认）：

1. **抽 `ContextTrimmingPort` 到 `contracts/runtime/`** — 10 methods 接口，含 `estimateTokens` / `isOverThreshold` / `microCompact` / `fullCompact` / `handoffCompact` / `applyHandoff` 等
2. **抽 `CompactSummary` record 到 `contracts/runtime/`** — 从 ContextCompactor 嵌套 record 提升为顶层
3. **改 `PreReasoningHook.beforeLlm` 签名**：`(List<Message>, int, ContextCompactor)` → `(List<Message>, int, ContextTrimmingPort)`（方案 Y：弱化 hook 对具体类型的依赖）
4. **`ContextCompactor implements ContextTrimmingPort`** 后 6 类一起 `git mv` 到 `context/` 子包
5. **ArchUnit 规则 3 启用**（context/ 不依赖 react/ 或 harness/）— frozen baseline 10 violations，将来 Wave 1.5 Port 收敛时回落到 0

**实测工作量**：0.5 人周（plan 估 0.5-0.8）。
**SDK 测试 109/109 通过**，react/ → harness/ 冻结库重置（371 → 372，新签名导致 frozen entry 过期）。
**commit**：`613638e` on `feature/wave-1-session-loop`，详见 [WAVE-1-SESSION-LOOP-DESIGN.md](./WAVE-1-SESSION-LOOP-DESIGN.md) §1。

---

*侦察稿 v2，所有断言基于代码快照（2026-07-07 develop）+ 实测验证。context/ 拆分阻断已记录在 §9。*
