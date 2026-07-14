# GNEX 智能引擎层（④ 运行时）架构评审文档

> ⚠️ **本文档定位为评审记录**（§1-2 评审流程、§6 跨团队契约、§7 NFR+验收方式、§8 风险、§10 测试、§11 检查清单、§12 评审意见）。
> §3-5 / §9 已转指针（与 LAYER.md / RUNTIME-LAYER.md 重复内容已下沉），以 [INTELLIGENT-ENGINE-LAYER.md](./INTELLIGENT-ENGINE-LAYER.md) 为 SSOT。

| 项 | 内容 |
|----|------|
| **文档版本** | v1.2 |
| **评审日期** | 2026-06-29 |
| **评审对象** | 智能引擎层 = **④ `d4-runtime`** + **`libs/gnex-agent-sdk`** |
| **产品 SSOT** | [ARCHITECTURE.md](./ARCHITECTURE.md)（原 GNexCore架构设计_2.1.html 已不在仓库） |
| **设计详述** | [INTELLIGENT-ENGINE-LAYER.md](./INTELLIGENT-ENGINE-LAYER.md) · [RUNTIME-LAYER.md](./RUNTIME-LAYER.md) |
| **建议读者** | 架构组、③ 编排 / ⑤ 注册 / ⑦ 沙箱 Owner、Tech Lead |

**术语**：正文称 **接口**（`gnex-contracts` 的 Java `interface`）；类名保留 `*Port` 后缀。**接口 = Port**（跨层边界）。

---

## 1. 评审目的

1. **确认 Owner 边界**：智能引擎层仅负责 ReAct 执行内核，不含 ② 接入、③ 编排、⑤ 注册。  
2. **对照 2.1 定稿**：产品层「智能引擎层」中 **推理引擎 · 记忆与上下文 · 动作派发** 的落地程度与差距。  
3. **冻结接口契约**：与 ③⑤⑦⑧⑨ 的接口边界，支撑 AgentOS 拆分并行开发。  
4. **排期 Backlog**：P1–P3 演进项与跨团队依赖。

---

## 2. 评审结论摘要

| 维度 | 结论 | 说明 |
|------|:----:|------|
| **Owner 边界** | ✅ 通过 | 范围限定为 ④ + SDK；②③⑤ 职责已划出 |
| **2.1 执行内核（§5.1.4）** | ✏️ 有条件通过 | ReAct 主链已落地；StatePort/Steering 双通道/WebSocket 原语等为目标态 |
| **工程可维护性** | ✅ 通过 | `gnex-agent-sdk` 抽离进行中；接口收口 Phase 23–27 已完成 |
| **跨层接口** | ✏️ 有条件通过 | ③ 须经 `CoordinatorRuntimePort` 调用；⑤ 仅消费接口，禁止直 import |
| **2.1 全量 Agent 引擎** | — 不适用 | 编排·协作·注册属 ③⑤，不在本次评审交付范围 |

> **本次评审范围（显式声明）**  
> 对照 2.1 仅覆盖：**Loop 1 执行循环**（§5.1.4 ReAct 内核）+ **PREP / act 派发** + **同步 Worker 子 ReAct**。  
> **不含**：Loop 2 校验循环 · Loop 3 事件驱动 · §5.1.2 编排模式 / 入口门禁 · §5.1.5 多 Agent 拓扑（消息总线） · Agent 注册与 Harness 适配（③⑤）。  
> 对外汇报建议用语：**「Agent 执行内核（ReAct Runtime）」**，避免与 2.1 产品层「智能引擎层」全称混淆。

**总体意见**：当前 GNEX **ReAct 主链路 MVP 已具备**，可继续 dev-assembler 单体与 Chat E2E；**交互与时态语义**（Steering 双通道、run 级 deadline、挂起外化）仍差一截，见 §5.3、§11.2 未验收项。与 2.1 目标态差距已文档化；Redis 热状态、远程沙箱、7 原语 API **明确后置**（[AGENTOS-SPLIT.md §12](./AGENTOS-SPLIT.md)）。

---

## 3. Owner 范围（评审确认项）

> **完整内容见** [INTELLIGENT-ENGINE-LAYER.md §1.2-1.5](./INTELLIGENT-ENGINE-LAYER.md)（含/不包含项 + 边界铁律）。
> 评审确认：④ 仅 Owner ReAct 执行内核；②③⑤⑦ 职责已划出，铁律已纳入 §11.2-U1 验收项。

---

## 4. 架构概要

> **完整内容见** [INTELLIGENT-ENGINE-LAYER.md §1.3 + §3 + §4.4](./INTELLIGENT-ENGINE-LAYER.md)（层间位置 + 组件图 + 三条执行路径）。
> 评审确认：架构图与门面 API 满足 ③⑤⑦ 联调需要，详见 §6 跨团队接口契约。

---

## 5. 与 GNexCore 2.1 差距评审

> **完整矩阵见** [RUNTIME-LAYER.md §11](./RUNTIME-LAYER.md)（2.1 差距矩阵 ④ Owner 项 2.0 更新）。
> 评审确认：✅/✏️/☐/— 分布与 RUNTIME-LAYER §11 一致；☐ 项后置排期见 §9 / [AGENTOS-SPLIT §12](./AGENTOS-SPLIT.md)。

---

## 6. 跨团队接口契约

### 6.1 ③ 编排 → ④ 运行时（调用方）

| 接口 | 方法 | SLA / 约定 |
|------|------|-----------|
| `CoordinatorRuntimePort` | `runCoordinatorReAct` / `resume*` | 调用前必须装配 `AgentExecutionContext` |
| `AgentRuntimePort` | `delegateToWorker` | 最小委派面；⑧ Bus 同此 |
| `AgentSyncDelegationPort` | Worker 同步路径 | 含 steeringSupplier |
| — | `ReActLoop.execute` | Scheduler 直调；③ Owner 调度逻辑 |

**③ 不得**：import `com.gnex.agent.runtime.AgentRuntime` 具体类。

### 6.2 ④ → ⑤ 注册（消费方）

| 接口 | 用途 |
|------|------|
| `LlmConfigPort` | ChatModel |
| `AgentRegistryPort` / Loader | Agent 定义 |
| `AgentToolBootstrapPort` | `ToolCallback[]` |
| `ToolHookPort` | ACT 前后 Hook |

**④ 不得**：实现注册 REST；不得 import `d5-registry` 实现包。

### 6.3 ④ → ⑦ 沙箱

| 接口 | 时机 |
|------|------|
| `InspectorChain.inspect` | 每次 tool call |
| `ToolExecutionGateway` | 实际执行 |
| `ConfirmationGateway` | CRITICAL 工具（经 ② SSE 闭环） |

### 6.4 ② → ④（控制面，非编排）

| 接口 | 用途 |
|------|------|
| `ChatConcurrencyPort` | 全局/会话锁 |
| `ChatInFlightControlPort` | steering / cancel |
| `ReActCheckpointQueryPort` | 断点查询 |

### 6.5 失败与责任（联调最小约定）

完整契约见 **[RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md)** §3–§6。摘要：

| 场景 | 期望行为 | 责任方 |
|------|----------|--------|
| ③ 未装配 `AgentExecutionContext` 即调用 Runtime | ④ fast-fail，明确异常 | ③ 保证装配；④ 文档化前置条件 |
| ⑤ LLM / Tool 装配失败 | 本 turn 失败，ERROR 事件，不 silent fallback | ⑤ 配置；④ 上报 |
| CRITICAL 工具未确认或超时 | ⑦→② 闭环；④ 响应 cancel | ②⑦ 主导 |
| steering 在长 tool 执行中到达 | **现状**：下一 turn 生效；**目标**：WebSocket cancel（P3） | 评审接受现状 |

---

## 7. 非功能需求与验收标准

| 指标 | 目标 | 验收方式 |
|------|------|----------|
| ReAct 上限 | 20 turns / 100 tool calls | 单测 + 配置常量 |
| Chat 并发 | 全局 8，session 串行 | `MessageQueueDualLaneTest` |
| 断点恢复 | true resume（messages 一致） | checkpoint 往返集成测 |
| LLM 保护 | 限流 + 熔断 | `gnex.llm.*` 配置 + 单测 |
| 模块边界 | ④ 零 ③⑤ 实现 import | Maven Enforcer（`bannedDependencies`）+ `SdkArchitectureTest`（15 ArchUnit 规则） |
| 编译 | `mvn -DskipTests compile` | CI |
| 回归 | Chat 全链路不退化 | dev-assembler E2E（②③ 驱动） |

---

## 8. 风险与依赖

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | `MessageQueue` 曾误划 d3，职责混淆 | 并行开发冲突 | 已修正 SSOT；MQ 归 SDK |
| R2 | steering 仅 turn 边界，长 tool 无法即时打断 | 体验劣于 2.1 | P1 EventLoop；远期 WebSocket cancel |
| R3 | ⑤ 接口变更未先改 contracts | ④ 编译失败 | contracts PR + CODEOWNERS |
| R4 | glue 仍留 agent-service | SDK 边界模糊 | P1 下沉 `AgentSyncExecutor` |
| R5 | 2.1 要求 Redis 热状态，现状 SQLite | 多副本扩展 blocked | 明确 Split-Phase 7，当前单体不受影响 |

**外部依赖**：③ 正确装配 Context 与 Tool；⑤ 提供稳定接口 Mock/实现；⑦ InspectorChain 行为不变。

---

## 9. 演进路线

> **完整 Backlog 见** [INTELLIGENT-ENGINE-LAYER.md §11](./INTELLIGENT-ENGINE-LAYER.md)（P1/P2/P3 项 + Owner）。
> 评审确认：P1 SessionLoop / SDK 边界 / Enforcer 排期与资源见 §11.2 未验收项跟踪表。

---

## 10. 测试与质量

| 层级 | Owner | 要求 |
|------|-------|------|
| Turn 内核单测 | ④ | guards、CompletionGate、Compactor |
| MQ 双 Lane | ④ | steering 优先级、session 串行 |
| Mock ③ 集成 | ④ | 不启真实 Orchestrator |
| 编排 E2E | ③ | `d3-orchestration-api.spec.ts` |
| 全链路 E2E | ②+③ | Chat 不退化 |

**④ 单测原则**：禁止 import `d5-registry` 实现；⑤ 能力一律 Mock 接口。

---

## 11. 评审检查清单

评审人请逐项勾选：

- [ ] **范围**：确认 ④ 不含 ②③⑤，与本文 §3 一致  
- [ ] **2.1 对齐**：接受 §5 差距矩阵；☐ 项后置排期无异议  
- [ ] **7 原语不采纳**：与 AGENTOS-SPLIT §12 决策一致  
- [ ] **接口契约**：§6 与 [RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md) 满足 ③⑤⑦ 联调需要  
- [ ] **MQ 归属**：`MessageQueue` 归 SDK/④，不归 ③  
- [ ] **Scheduler 归属**：`AgentScheduler` 归 ③，仅调用 `execute`  
- [ ] **NFR**：§7 指标可验收  
- [ ] **风险**：§8 缓解措施可接受  
- [ ] **P1 Backlog**：§9.1 资源与优先级确认  
- [ ] **未验收项**：知悉 §11.2 在签字时尚未闭环，不视为已交付  

### 11.2 未验收项（签字时不视为已完成）

以下写在设计或 Backlog 中，**Enforcer / CI 尚未证明**，评审通过 ≠ 已落地：

| # | 项 | 现状 | 计划验收 |
|---|-----|------|----------|
| U1 | Maven Enforcer 禁 ③⑤ import | ✅ **已落地**：`libs/gnex-agent-sdk/pom.xml` 配 `maven-enforcer-plugin`（`bannedDependencies` 禁 `com.gnex:*-service` + `gnex-sandbox-runtime`）；`SdkArchitectureTest`（15 ArchUnit 规则）冻结内部包边界（react↔harness、boundary→react、memory→react 等） | ✅ `mvn verify`（SDK 模块） |
| U2 | `AgentSyncExecutor` 完全在 SDK | ✅ **已落地**：`AgentSyncExecutor.java` 从 `services/gnex-agent-service/src/main/java/com/gnex/agent/runtime/` 迁入 `libs/gnex-agent-sdk/src/main/java/com/gnex/agent/runtime/`（包名不变，`@Component` 由 SDK 提供，agent-service 通过 Spring component scan 自动注入） | ✅ `mvn -pl libs/gnex-agent-sdk,services/gnex-agent-service test`（454+955 通过） |
| U3 | SessionLoop | 设计 SSOT 已定稿；`loop/` 包已落地（Wave 2-4 Phase 2a 完成；Phase 2b `AgentInboxLoop` 在 services 层） | ✅ Phase 2a 已完成；Phase 2b 跨节点延后 v2.1+ |
| U4 | run 级 deadline | ✅ **已落地**：`AgentExecutionContext.runDeadlineAt` (Instant) + `ChatRunContext.getRunDeadlineAt()` 接口；`ReActTurnPreamble.checkPreLlmGuards()` 每 turn 检查；超时 → `ReActResult` + 状态 `RUN_DEADLINE_EXCEEDED` + `recordReactEnd("run_deadline_exceeded",...)`；`gnex.runtime.run-deadline.seconds` 配置（0=禁用，默认禁用以兼容历史）；`ChatRunContextPortAdapter.create()` 自动按配置注入 deadline | ✅ `mvn -pl libs/gnex-agent-sdk test`（494/494 通过，含 3 个 U4 新用例） |
| U5 | Steering WebSocket cancel | ✅ **引擎侧 scaffold 已落地**（U5-prep）：`ToolAbortPort` + `InFlightToolCallRegistry`（`abortBySession` 设 cancelled flag + `worker.interrupt()`）；`ReActToolActPhase` post-execute guard。详见 `EXECUTION-ENGINE-SPEC.md §5.7`。WebSocket endpoint 缺 access 层 | P3 + ⑦ |
| U6 | StatePort / Redis 热路径 | SQLite checkpoint | Split-Phase 7 |
| U7 | 跨层失败形态单测 | ✅ **已落地**：`libs/gnex-agent-sdk/.../harness/RuntimeFailureContractsTest`（6 个用例覆盖 §6.5 #1-4：① 未装配 Context fast-fail / resume 路径同 guard / assembled-pass-through / Inspector 抛错→DENY / CRITICAL 工具默认 DENY / steering 现状下一 turn 生效契约锚点）；`AgentRuntime.runCoordinatorReAct` 与 `resumeCoordinatorReAct` 加入 `requireAssembledContext()` 前置 guard | ✅ `mvn -pl libs/gnex-agent-sdk test`（494/494 通过，本会话持续加固：U7 6 + U4 3 + §5.6 1 + §6.2 5 共 15 用例新增） |

---

## 12. 评审意见记录

| 评审人 | 角色 | 意见 | 结论 | 日期 |
|--------|------|------|------|------|
| | 架构 | | ☐ 通过 ☐ 有条件通过 ☐ 不通过 | |
| | ③ 编排 | | ☐ 通过 ☐ 有条件通过 ☐ 不通过 | |
| | ⑤ 注册 | | ☐ 通过 ☐ 有条件通过 ☐ 不通过 | |
| | ⑦ 沙箱 | | ☐ 通过 ☐ 有条件通过 ☐ 不通过 | |
| | Tech Lead | | ☐ 通过 ☐ 有条件通过 ☐ 不通过 | |

**遗留项跟踪**（评审后填写）：

| ID | 描述 | Owner | 目标日期 | 状态 |
|----|------|-------|----------|------|
| | | | | |

---

## 13. 附录：文档索引

| 文档 | 用途 |
|------|------|
| [RUNTIME-CONTRACTS.md](./RUNTIME-CONTRACTS.md) | **跨层契约 SSOT**（RC-01–RC-11） |
| [INTELLIGENT-ENGINE-LAYER.md](./INTELLIGENT-ENGINE-LAYER.md) | 设计详述（Owner 边界 + 组件 + API） |
| [RUNTIME-LAYER.md](./RUNTIME-LAYER.md) | 类级职责 + **§9 2.1 差距矩阵** |
| [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) | EventLoop P1 演进 SSOT |
| [AGENTOS-SPLIT.md](./AGENTOS-SPLIT.md) | 拆分阶段与不采纳项决策 |
| [LAYER-ARCHITECTURE.md](./LAYER-ARCHITECTURE.md) | 九层工程边界 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 产品/技术架构 SSOT（替代已移除的外部 HTML） |

---

*本文档为架构评审专用摘要；实现细节以 RUNTIME-LAYER.md 为准，Owner 边界以 INTELLIGENT-ENGINE-LAYER.md 为准。*
