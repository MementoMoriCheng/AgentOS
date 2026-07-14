# D3 编排层接口参考

> **版本**：v1.0（2026-07-01）
> **Owner**：③ 编排层 + `gnex-agent-service` + `gnex-platform-service/workflow`
> **代码 SSOT**：`libs/gnex-contracts/.../orchestration/`（Java `interface` 定义处，31 文件）
> **契约 SSOT**：[d3-orchestration-design.md](./d3-orchestration-design.md) v2.0
> **架构 SSOT**：[ORCHESTRATION-LAYER.md](./ORCHESTRATION-LAYER.md)

> ⚠️ **本文档是查询表**：仅列方法名、方向、参数概要。**完整方法签名 / 前置后置条件 / 失败语义 SSOT = `d3-orchestration-design.md`**（OC 编号体系）。当两份文档方法签名出现冲突时，以 d3 为准；本文应被修正。

本文按**上层/下层**视角列出 D3 编排层的全部 Port 接口。每个接口包含方法签名、入参出参、前置条件、后置条件、失败语义。

**符号说明**：
- ✓ 必填 | ○ 可选 | ⚠ 条件必填
- 前置 = 调用前必须成立 | 后置 = 调用后保证成立 | 失败 = 异常或异常返回值

---

## 1. 上层接口（D3 暴露，② 消费）

### 1.1 核心编排

#### ChatOrchestrationPort

> 消费方：② `ChatAgentStreamRunner` | 实现方：③ `Orchestrator` | 包：`contracts.orchestration` | OC-01

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `processStream` | `userInput` ✓, `sseSessionId` ✓ | `String` | `ChatRunContext` 已绑定；全局+session 锁已 acquire；入口门禁已通过 | 返回最终回答文本；checkpoint COMPLETED 或 RESUMABLE | 预算拒绝→RC-08 拦截；cancel→`OperationCancelledException`；LLM/工具→ERROR 事件 |
| `resumeFromCheckpoint` | `checkpoint` ✓, `sseSessionId` ✓ | `String` | checkpoint.isResumable()==true | 恢复编排完成文本 | checkpoint 非法→`IllegalArgumentException` |

**意图路由流水线**：Capability Inquiry 检测 → Multi-step 检测(PlanExecutor) → Direct Delegation(confidence>=0.7) → NO_MATCH(DirectAnswer) → 默认 ReAct

#### ChatUserIntentPort

> 消费方：② `ChatAgentStreamRunner` | 实现方：③ `ChatUserIntentPortAdapter` | 包：`contracts.orchestration` | OC-03

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `isMcpCatalogRequest` | `userText` ✓ | `boolean` | — | true=用户正在查询 MCP 服务器目录 | — |
| `isSkillCatalogRequest` | `userText` ✓ | `boolean` | — | true=用户正在查询 Skill 目录 | — |
| `publishSkillCatalogPreviewIfRequested` | — | void | — | 若匹配，Skill 目录预览已推送给 SSE | — |

#### OrchestratorPromptPort

> 消费方：③ `Orchestrator` | 实现方：③ `OrchestratorPromptLoader` | 包：`contracts.orchestration` | OC-02

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `loadSystemPrompt` | — | `String` | — | 完整编排系统提示词；`UNIVERSAL_SECTIONS`(10 节)受保护不可覆写 | — |

---

### 1.2 Team 协作

#### AgentTeamManagementPort

> 消费方：② `TeamController` | 实现方：③ `AgentTeamManagementPortAdapter` → `AgentTeamService` | 包：`contracts.orchestration.team` | OC-04

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `createTeam` | `name` ✓, `leaderAgent` ✓, `description` ○, `members` ○ | `TeamDetail` | leaderAgent 存在 | Team 已创建 + 初始成员已加入 | leaderAgent 不存在→异常 |
| `listTeams` | — | `List<TeamDetail>` | — | 全部 Team（含成员） | — |
| `getTeam` | `teamId` ✓ | `@Nullable TeamDetail` | — | Team 详情（含成员） | teamId 不存在→null |
| `archiveTeam` | `teamId` ✓ | void | — | Team 已标记 ARCHIVED | — |
| `addMember` | `teamId` ✓, `agentName` ✓, `role` ○ | `TeamMember` | agent 存在 | 成员已加入 | agent 不存在→异常 |
| `removeMember` | `teamId` ✓, `agentName` ✓ | void | 成员存在 | 成员已移除 | 成员不存在→静默 |
| `pauseTeam` | `teamId` ✓ | `TeamDetail` | team 存在且非 ARCHIVED | Team 状态=PAUSED | — |
| `resumeTeam` | `teamId` ✓ | `TeamDetail` | team 存在 | Team 状态=ACTIVE | — |
| `registerTagRoute` | `teamId` ✓, `tag` ✓, `agentName` ✓, `priority` ✓ | void | — | 标签路由已注册 | — |
| `listTagRoutes` | `teamId` ✓ | `List<TeamTagRoute>` | — | 全部标签路由 | — |
| `deleteTagRoute` | `teamId` ✓, `tag` ✓ | void | — | 标签路由已删除 | — |
| `routeTask` | `teamId` ✓, `requiredTag` ○ | `@Nullable String` | — | 目标 Agent 名称 | 无可用成员→null |
| `executeBatch` | `teamId` ✓, `tasks` ✓, `maxConcurrent` ✓ | `BatchResult` | — | 同步批量执行结果 | — |
| `executeBatchAsync` | `teamId` ✓, `tasks` ✓, `maxConcurrent` ✓ | `BatchResult` | — | 异步批量提交结果 | — |
| `getTeamConfig` | `teamId` ✓ | `Map<String, Object>` | — | Team JSON 配置 | — |
| `updateTeamConfig` | `teamId` ✓, `configJson` ✓ | void | — | Team 配置已更新 | — |
| `recordTeamSkill` | `teamId` ✓, `skillName` ✓, `description` ○, `sourceAgent` ✓ | void | — | Skill 使用计数+1 | — |
| `listTeamSkills` | `teamId` ✓ | `List<TeamSkill>` | — | 全部 Team 技能 | — |
| `recommendSkills` | `teamId` ✓, `agentName` ✓ | `List<TeamSkill>` | — | 按用量排序的推荐列表 | — |
| `getTeamSkillStats` | `teamId` ✓ | `Map<String, Object>` | — | 技能统计数据 | — |
| `applyRecommendedSkills` | `teamId` ✓, `agentName` ✓ | `List<SkillApplyResult>` | — | 推荐技能批量安装结果 | — |
| `applySkillToMember` | `teamId` ✓, `agentName` ✓, `skillName` ✓ | `SkillApplyResult` | skill 已注册 | 技能已安装 | — |

**嵌套类型**：`TeamDetail(AgentTeam team, List<TeamMember> members)`、`BatchResult(String teamId, List<BatchTaskAssignment> assignments, int totalTasks, int memberCount)`

#### TeamTaskRoutingPort

> 消费方：③ 内部 | 实现方：③ `AgentTeamService` | 包：`contracts.orchestration` | OC-05

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `routeTask` | `teamId` ✓, `requiredTag` ○ | `@Nullable String` | — | 目标 Agent 名称 | 无可用成员→null |
| `routeToLeader` | `teamId` ✓ | `@Nullable String` | — | Leader Agent 名称 | leader 不可用→null |
| `executeBatchAsync` | `teamId` ✓, `tasks` ✓, `maxConcurrent` ✓ | `BatchResult` | — | 批量提交结果 | — |
| `executeBatchAsync`(with batchId) | `teamId` ✓, `tasks` ✓, `maxConcurrent` ✓, `batchId` ✓ | `BatchResult` | — | 指定批次 ID 的提交结果 | — |
| `cancelBatch` | `teamId` ✓, `batchId` ✓ | void | 批次存在 | 批次所有 Future 已取消 | 批次不存在→静默 |

**路由算法**：Tag 精确路由 → 健康过滤(successRate>=0.5, lookback=10) → 最少 pending 消息 → 兜底 leader

#### TeamObservabilityPort

> 消费方：② `TeamObservabilityController` | 实现方：③ `TeamObservabilityPortAdapter` → `TeamObservabilityService` | 包：`contracts.orchestration.team` | OC-06

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getDashboard` | `teamId` ✓ | `@Nullable Dashboard` | — | Team 看板数据（成员状态、成功率、pending 消息） | teamId 不存在→null |
| `compareTeams` | — | `List<Summary>` | — | 所有 Team 概要对比 | — |
| `getHistory` | `teamId` ✓, `days` ✓ | `@Nullable HistoryChart` | — | 指定天数的历史趋势 | teamId 不存在→null |
| `getHistoryEntries` | `teamId` ✓, `days` ✓ | `List<HistoryEntry>` | — | 每日条目列表 | — |
| `compareTeamsByIds` | `teamIds` ✓ | `ComparisonResult` | — | 指定 Team 的指标对比 | — |

#### TeamMentionParserPort

> 消费方：③ 内部 | 实现方：③ `TeamMentionParser` | 包：`contracts.orchestration` | OC-15

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `parse` | `message` ✓ | `List<TeamMentionRecord>` | — | 解析出的 `@Team` 提及列表 | 无提及→空列表 |

**嵌套类型**：`TeamMentionRecord(String teamName, String teamId, String mentionText, String teamStatus)`

---

### 1.3 Team 协作空间（原 Room）

Room 的概念已合入 Team——协作空间是 Team 的一项子能力，不再是一级概念。原 `AgentRoomManagementPort` 演进为 `TeamCollaborationManagementPort`。

#### TeamCollaborationManagementPort

> 消费方：② `TeamController` | 实现方：③ `AgentRoomService` | 包：`contracts.orchestration` | OC-07

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `openCollaboration` | `taskSummary` ✓, `sessionId` ✓, `roles` ✓ | `CollaborationDetail` | session 存在 | 协作空间已创建，4 阶段 DAG 节点已初始化（均为 PENDING） | — |
| `listCollaborations` | `status` ○ | `List<Collaboration>` | — | 按状态过滤的协作列表 | — |
| `getCollaboration` | `collabId` ✓ | `@Nullable CollaborationDetail` | — | 协作详情 + DAG 节点 | collabId 不存在→null |
| `updateCollaborationStatus` | `collabId` ✓, `status` ✓ | void | 协作存在 | 状态已更新(OPEN→CONVERGED/CLOSED) | — |
| `completeNode` | `nodeId` ✓, `evidence` ✓ | `DagNode` | 前序节点均 DONE | 节点标记 DONE，evidence 持久化到记忆 | 前序未完成→`IllegalStateException` |
| `markNodeNoReply` | `nodeId` ✓ | `DagNode` | — | 节点标记 NO_REPLY | — |

**4 阶段 DAG**：`DECISION → CONTRACT → IMPLEMENT → VERIFY`（依赖链：前序 DONE 才能激活后序）

---

### 1.4 Workflow

#### WorkflowManagementPort

> 消费方：② `WorkflowController` | 实现方：③ `WorkflowManagementPortAdapter` → `WorkflowService` | 包：`contracts.orchestration` | OC-16

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listDefinitions` | — | `List<DefinitionView>` | — | 全部工作流定义 | — |
| `getDefinition` | `id` ✓ | `@Nullable DefinitionView` | — | 工作流定义 | id 不存在→null |
| `createDefinition` | `name` ✓, `description` ✓, `definition` ✓(JSON), `createdBy` ✓ | `DefinitionView` | JSON 格式合法 | 定义已创建，初始状态 DRAFT | JSON 不合法→异常 |
| `updateDefinition` | `id` ✓, `name` ✓, `description` ✓, `definition` ✓ | `@Nullable DefinitionView` | 定义存在 | 定义已更新 | id 不存在→null |
| `publishDefinition` | `id` ✓ | `boolean` | 定义存在 | true=已发布(DRAFT→PUBLISHED) | — |
| `archiveDefinition` | `id` ✓ | `boolean` | — | true=已归档(PUBLISHED→ARCHIVED) | — |
| `startInstance` | `definitionId` ✓ | `InstanceView` | definition 状态=PUBLISHED | 实例已启动，状态=RUNNING | definition 未发布→异常 |
| `getInstance` | `id` ✓ | `@Nullable InstanceView` | — | 实例详情 | id 不存在→null |
| `listAllInstances` | — | `List<InstanceView>` | — | 全部实例 | — |
| `listInstances` | `definitionId` ✓ | `List<InstanceView>` | — | 指定定义的实例 | — |
| `getNodeLogs` | `instanceId` ✓ | `List<NodeLogView>` | — | 节点执行日志 | — |
| `resumeInstance` | `instanceId` ✓, `decision` ✓, `userId` ✓ | void | instance 状态=PAUSED、decision=APPROVED/REJECTED、用户有 approval:resolve 权限 | 审批节点已恢复执行 | 用户无权限→异常 |
| `cancelInstance` | `instanceId` ✓ | `boolean` | — | true=实例已取消 | — |

**节点类型**：`START → TOOL/AGENT/FORK/APPROVAL/SQUAD → END/JOIN`
**执行模型**：`parseGraph` → `executeFromNode` [virtual thread] → 逐节点推进，FORK 并行分支，APPROVAL 阻塞等待。

#### AgentFlowPlanPort

> 消费方：② `PlanController` | 实现方：③ `AgentFlowPlanPortAdapter` → `AgentFlowEngine` | 包：`contracts.orchestration` | OC-17

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `startPlan` | `goal` ✓ | `@Nullable String` | goal 非空 | planId（非 null=成功，null=LLM 生成失败） | — |
| `getPlan` | `planId` ✓ | `@Nullable PlanView` | — | Plan 视图（包含 tasks） | planId 不存在→null |
| `getAllPlans` | — | `List<PlanView>` | — | 全部 Plan | — |

**执行模型**：`PlanGenerator.decompose(goal)` → 依赖拓扑排序 → 虚拟线程并行 → 失败重试(max 2) → 全阻塞时 regenerate(max 2)

---

### 1.5 Adapter 虚拟层

#### AgentAdapterPort

> 消费方：② `AdapterController` | 实现方：③ `AgentAdapterExecutor` | 包：`contracts.orchestration.adapter` | OC-08

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `convert` | `format` ✓, `sourcePath` ✓ | `Object` | 胶水脚本 `gnex-adapter-{format}.py`/`.js` 存在于 `~/.gnex/adapters/` | 返回 `CanonicalAgent`（运行时类型） | `AdapterNotFoundException`(脚本不存在)→`AdapterExecutionException`(超时/非零退出)→`AdapterParseException`(stdout 非 JSON) |

**异常**：
- `AdapterNotFoundException` — `getAdapterPath()` 返回缺失路径
- `AdapterExecutionException` — `getExitCode()` 非零退出 / 超时强杀
- `AdapterParseException` — stdout 非 `CanonicalAgent` JSON

---

### 1.6 辅助编排

#### DevMapPort

> 消费方：② `DevMapController` | 实现方：③ `DevMapPortAdapter` → `DevMapService` | 包：`contracts.orchestration` | OC-09

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `generateDevMap` | `projectId` ✓ | `DevMap` | — | 项目全景图(agents/skills/workflows/sessions) | — |
| `generateTaskBoard` | `projectId` ✓ | `TaskBoardView` | — | 任务看板(workflow instances/chat sessions) | — |

#### OutputChannelPort

> 消费方：③ 内部 | 实现方：③ `OutputChannelService` → `OutputChannelRecorder` | 包：`contracts.orchestration` | OC-10

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `recordToolOutput` | `agentId` ✓, `projectId` ✓, `toolName` ✓, `arguments` ✓, `result` ✓, `durationMs` ✓ | void | — | 工具输出已记录到 `execution_log`（类型=LOG） | — |
| `recordAs` | 同上 + `preferredType` ✓ | void | — | 指定 OutputType 的工具输出记录 | — |

**`OutputType` 枚举**：`WORKSPACE`, `REPORT`, `LOG`, `MESSAGE`

#### SessionGoalPort

> 消费方：③ `OrchestratorInputAugmenter` | 实现方：③ `SessionGoalPortAdapter` | 包：`contracts.orchestration` | OC-11

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `setGoal` | `sessionId` ✓, `goal` ○ | void | — | Session 级目标已持久化（注入到 system prompt 尾部） | — |
| `getGoal` | `sessionId` ✓ | `@Nullable String` | — | 当前 Session 目标 | session 不存在→null |

#### HandoffArtifactPort

> 消费方：③ `WorkflowEngine` | 实现方：③ `HandoffArtifactService` | 包：`contracts.orchestration` | OC-12

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `save` | `runId` ✓, `sessionId` ✓, `sourceNode` ✓, `targetNode` ✓, `brief` ✓ | void | — | Handoff 产物已持久化 | — |
| `loadLatest` | `runId` ✓ | `HandoffBrief` | — | 最新 Handoff 产物 | 无产物→空 HandoffBrief |

**嵌套类型**：`HandoffBrief` 定义在 `gnex-contracts/runtime/`（与 D4 共享）

---

### 1.7 调度与 Job

#### AlwaysOnTaskManagementPort

> 消费方：② `AlwaysOnController` | 实现方：③ `AlwaysOnTaskManagementPortAdapter` → `AlwaysOnTaskService` | 包：`contracts.orchestration` | OC-13

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `create` | `request` ✓(CreateTaskRequest) | `Task` | — | 常驻任务已创建，状态=ACTIVE | — |
| `listTasks` | — | `List<Task>` | — | 全部常驻任务 | — |
| `findByTaskId` | `taskId` ✓ | `@Nullable Task` | — | 指定任务 | taskId 不存在→null |
| `listRuns` | `taskId` ✓, `limit` ✓ | `List<Run>` | — | 最近 N 次运行记录 | — |
| `pause` | `taskId` ✓ | void | 任务存在 | 状态=PAUSED，调度器跳过 | — |
| `resume` | `taskId` ✓ | void | 任务存在 | 状态=ACTIVE | — |
| `deleteByTaskId` | `taskId` ✓ | void | — | 任务已删除 | — |

**状态机**：`ACTIVE ──tryMarkRunning──→ RUNNING ──completeRun──→ ACTIVE`
**乐观锁**：条件 UPDATE `status=ACTIVE→RUNNING`，影响 0 行时放弃

#### AgentJobManagementPort

> 消费方：② `JobController` | 实现方：③ `AgentScheduler` | 包：`contracts.orchestration` | OC-14

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `submit` | `agentName` ✓, `taskDescription` ✓, `priority` ✓, `sseSessionId` ✓, `depth` ✓ | `String` | agentName 已注册；depth < maxDepth(3) | jobId 已返回，异步执行中 | depth 超限→拒绝；agent 不存在→异常 |
| `getStatus` | `jobId` ✓ | `@Nullable AgentJobRecord` | — | Job 状态记录 | jobId 不存在→null |
| `cancel` | `jobId` ✓ | `boolean` | — | true=Job 已取消 | — |
| `pause` | `jobId` ✓ | `boolean` | — | true=Job 已暂停 | — |
| `resume` | `jobId` ✓ | `boolean` | — | true=Job 已恢复 | — |

**优先级**：0-9，数值越高越优先。结果通过 SSE 推送。

---

## 2. 下层接口（D3 消费，④⑤⑥⑦⑧⑨ 实现）

### 2.1 ④ 运行时层

#### CoordinatorRuntimePort

> 实现方：④ `AgentRuntime` | 包：`contracts.runtime` | RC-01

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `runCoordinatorReAct` | `systemPrompt` ✓, `userInput` ✓ | `ReActResult` | `ChatRunContext` 已 bind | 最终文本 + token 用量；checkpoint COMPLETED/RESUMABLE | 预算拒绝→拦截；cancel→`OperationCancelledException` |
| `runDirectAnswer` | `systemPrompt` ✓, `userInput` ✓ | `ReActResult` | 同上 | 单轮 LLM，无工具，2-5s 完成 | 同上 |
| `resumeCoordinatorReAct` | `checkpoint` ✓ | `ReActResult` | checkpoint.isResumable()==true | 同 runCoordinatorReAct | checkpoint 非法→异常 |
| `publishRoutingToUi` | `match` ○ | void | SSE 已 attach | UI 收到 routing 事件 | SSE 断开→静默 |
| `delegateToWorker` | `targetAgent` ✓, `task` ✓ | `String` | Context.depth < maxDepth；agent 可解析 | Worker 最终文本 | agent 不存在→异常 |

**消费方**：③ `Orchestrator`(runCoordinatorReAct/runDirectAnswer/delegateToWorker)、`PlanExecutor`(delegateToWorker)、`AgentRouterTool`(runCoordinatorReAct)

#### AgentRuntimePort

> 实现方：④ `AgentRuntime` | 包：`contracts.runtime` | RC-02

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `delegateToWorker` | `targetAgent` ✓, `task` ✓ | `String` | Context.depth < maxDepth；agent 可解析 | Worker 最终文本 | agent 不存在→异常；超 depth→拒绝 |

**消费方**：③ `AgentCollaborator`、`WorkflowEngine.NodeExecutor`、`AgentFlowEngine`、`TeamBatchExecutor`

#### SessionLoopPort

> 实现方：④ (2.0 新增) | 包：`contracts.runtime` | RC-22

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `fireInbound` | `sessionId` ✓, `kind` ✓, `payload` ✓ | void | — | 事件入队，loop 唤醒 | — |
| `wakeUp` | `sessionId` ✓ | void | — | IDLE/YIELDING loop 被唤醒 | — |
| `isBusy` | `sessionId` ✓ | `boolean` | — | true=session 正处理中 | — |
| `getChannelStatus` | `sessionId` ✓ | `ChannelStatus` | — | channel 状态 | — |

**`InboundKind` 优先级**：`CANCEL(0)` > `STEERING(1)` > `USER_TURN(2)` > `FOLLOW_UP(3)` > `BUS_TASK(4)`
**消费方**：③ `Orchestrator`（SessionLoop 2.0 路径）

#### ChatRunContextPort

> 实现方：④ ThreadLocal | 包：`contracts.runtime` | RC-04

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `create` | — | `ChatRunContext` | — | 新 Context 实例 | — |
| `bind` | `context` ✓ | void | context 非 null | ThreadLocal 绑定完成 | — |
| `unbind` | — | void | 已 bind | ThreadLocal 清除 | — |

**消费方**：③ `Orchestrator`

#### ChatConcurrencyPort

> 实现方：④ `MessageQueue` | 包：`contracts.runtime` | RC-05

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `tryAcquireGlobal` | — | `boolean` | — | true=全局槽位已占；false=全局满 | — |
| `tryAcquireSession` | `sessionId` ✓ | `boolean` | — | true=session 独占锁已获；false=该 session 正忙 | — |
| `prepareForNewTurn` | `sessionId` ✓ | void | session 锁已 acquire | 清 cancel+steering 队列；保留 follow-up | — |
| `releaseSession` | `sessionId` ✓ | void | — | session 锁释放 | — |
| `releaseGlobal` | — | void | — | 全局槽位释放 | — |

**消费方**：③ `Orchestrator`（1.0 路径）

#### SessionFollowUpPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `markFollowUpPending` | `sessionId` ✓ | void | — | session 标记为有 follow-up 待处理 | — |
| `getAndClearFollowUp` | `sessionId` ✓ | `@Nullable String` | — | 待处理的 follow-up 文本 | 无 follow-up→null |

**消费方**：③ `OrchestratorInputAugmenter`

---

### 2.2 ⑤ 注册层（platform-service）

#### SkillRegistryPort

> 实现方：platform-service | 包：`contracts.registry` | RC-14

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `listAll` | — | `List<SkillRegistryRecord>` | — | 全部 Skill 注册记录 | — |
| `resolve` | `name` ✓ | `@Nullable SkillDefinition>` | — | Skill 定义 | name 不存在→null |
| `install` | `canonicalSkill` ✓ | `String` | — | 安装结果消息 | — |
| `uninstall` | `name` ✓ | `String` | skill 存在 | 卸载结果消息 | skill 不存在→异常 |

**消费方**：③ `AgentToolBootstrap`、`DevMapService`、`TeamSkillInstaller`

#### AutoSkillCatalogPort

> 实现方：platform-service | 包：`contracts.registry` | RC-17

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getAutoCatalogSection` | — | `String` | — | Auto skill 提示词段，注入 system prompt | — |
| `refreshCache` | — | void | — | 本地缓存刷新 | — |

**消费方**：③ `OrchestratorPromptLoader`

#### SkillOnDiskCatalogPort

> 实现方：platform-service | 包：`contracts.registry` | RC-18

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `scanDirectory` | `path` ✓ | `List<OnDiskSkill>` | — | 目录下的 Skill 列表 | — |

**消费方**：③ `TeamSkillInstaller`

#### AgentToolBootstrapPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `bootstrap` | `delegationTarget` ✓ | `AgentToolArrays` | Agent 定义已加载 | 返回 3 组 ToolCallback(static/coordinator/agentSafe) | bootstrap 异常→向上抛 |

**消费方**：③ `AgentSyncExecutor`、`AgentScheduler`、`LeaderRuntime`

#### AgentWorkerToolPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `createAgentTools` | `agentName` ✓ | `ToolCallback[]` | agent 在 ⑤ 可解析 | 该 Agent 工具集 | agent 不存在→空数组 |

**消费方**：③ `AgentSyncExecutor`、`AgentScheduler`、`LeaderRuntime`、`AlwaysOnRunner`

#### AgentWorkerToolConfiguratorPort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `configureAgentSafeCallbacks` | `agentSafeCallbacks` ✓ | void | — | Worker 安全工具回调配置完成 | — |

**消费方**：③ `AgentWorkerToolFactory`

#### ToolHookPort

> 实现方：platform-service `HookExecutor` | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `executeToolHook` | `phase` ✓, `agentName` ✓, `sessionId` ✓, `toolName` ✓, `arguments` ✓, `result` ○ | `ToolHookOutcome` | — | Hook 执行结果（可能修改参数或取消） | Hook 异常→按 ⑤ 策略 |

**嵌套类型**：`ToolHookPhase { PRE_TOOL_USE, POST_TOOL_USE }`、`ToolHookOutcome(String arguments, boolean cancelled)`

**消费方**：③ `AgentSyncExecutor`、`AgentScheduler`、`AsyncAgentExecutor`、`AlwaysOnRunner`

#### CustomToolManagementPort

> 实现方：platform-service | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `resolveCustomTool` | `name` ✓, `projectId` ✓ | `@Nullable CustomToolRecord` | — | Custom tool 查询结果 | — |

**消费方**：③ `AgentToolBootstrap`

#### LlmConfigPort / ModelConfigPort

> 实现方：⑤ (platform-service) | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getEffectiveDefaultModel` | — | `String` | — | 当前默认模型名 | — |
| `getModelForAgent` | `agentName` ✓ | `String` | — | 该 Agent 使用的模型 | — |
| `getAgentModelOverride` | `agentName` ✓ | `@Nullable String` | — | Agent 模型覆盖值 | — |

**消费方**：③ `AgentWorkerToolFactory`

---

### 2.3 ⑥ 治理层

#### AgentBudgetPort

> 实现方：agent-service `AgentBudgetService` | 包：`contracts.runtime` | RC-08

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `checkBudget` | `agentName` ✓, `projectId` ✓ | `@Nullable String` | — | null=允许执行；非 null=拒绝原因(如"daily budget exceeded") | — |
| `checkoutTokens` | `agentName` ✓, `projectId` ✓, `tokens` ✓ | `boolean` | — | true=扣费成功；false=扣费失败(记审计) | 扣费失败→false |

**消费方**：③ `AgentScheduler`、`AsyncAgentExecutor`、`Orchestrator`

#### ConfirmationPort

> 实现方：⑥ | 包：`contracts.governance`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `approve` | `confirmationId` ✓ | `boolean` | confirmation 存在且 PENDING | true=已批准 | ID 不存在→false |
| `reject` | `confirmationId` ✓ | `boolean` | 同上 | true=已拒绝 | 同上 |

**消费方**：③ `WorkflowApprovalGate`

---

### 2.4 ⑧ 总线层

#### MessageBusPort

> 实现方：bus-service | 包：`contracts.bus`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `publishAction` | `action` ✓ | void | — | action 已发布到总线 | — |
| `publishObservation` | `observation` ✓ | void | — | observation 已发布 | — |
| `awaitObservation` | `tenantId` ✓, `sandboxId` ✓, `requestId` ✓, `timeout` ✓ | `Optional<ObservationMessage>` | — | 对应 observation 或 empty | 超时→empty |
| `publish` | `event` ✓ | void | — | 事件已发布 | — |
| `subscribe` / `unsubscribe` | `topicPattern` ✓, `handler` ✓ | void | — | 订阅/取消订阅 | — |
| `pollAction` | `tenantId` ✓, `sandboxId` ✓, `consumerName` ✓ | `Optional<ActionMessage>` | — | 待处理 action | — |

**消费方**：③ `AgentTeamService`、`WorkflowSquadExecutor`

#### AgentCommunicationPort

> 实现方：bus-service | 包：`contracts.bus`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `dispatch` | `context` ✓(DispatchContext) | `DispatchReceipt` | — | 任务已分发 | 目标 agent 不存在→异常 |
| `await` | `taskId` ✓, `timeout` ✓, `onProgress` ○ | `SyncResult` | — | 同步等待结果 | 超时→status=TIMEOUT |
| `onEvent` | `agentName` ✓, `topicPattern` ✓, `handler` ✓ | `Subscription` | — | 事件监听已注册 | — |
| `cancel` | `taskId` ✓ | `boolean` | — | true=取消已接受 | — |

**消费方**：③ `PlanExecutor`(dispatch + await 模式)、`TeamBatchExecutor`

---

### 2.5 ⑨ 数据层

#### WorkflowQueryPort

> 实现方：platform-service | 包：`contracts.registry`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `findInstanceByRunId` | `runId` ✓ | `@Nullable InstanceView` | — | 工作流实例 | 无→null |
| `findNodeLogsByRunId` | `runId` ✓ | `List<NodeLogView>` | — | 节点日志 | — |

**消费方**：③ `PlanExecutor`、`DevMapService`（当前违规直写 mapper，目标态应使用此 Port）

#### ConversationAccessPort

> 实现方：agent-service | 包：`contracts.conversation`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `getSessionForUser` | `sessionId` ✓, `userId` ✓ | `ConversationSessionRecord` | session 存在 | 会话记录 | 无权限→异常 |
| `createSession` | `title` ✓, `mode` ✓, `createdBy` ✓ | `ConversationSessionRecord` | — | 新会话记录 | — |
| `addMessage` | `sessionId` ✓, `role` ✓, `content` ✓, `toolName` ○ | `Long` | — | 消息 ID | — |
| `getSessionMessages` | `sessionId` ✓ | `List<ConversationMessageRecord>` | — | 消息列表 | — |

**消费方**：③ `SessionManager`、`OrchestratorInputAugmenter`

#### MemoryQueryPort

> 实现方：agent-service | 包：`contracts.memory`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `query` | `q` ○, `source` ○, `page` ✓, `pageSize` ✓ | `Page` | — | L1 记忆分页 | — |
| `delete` | `id` ✓ | `boolean` | — | true=已删除 | — |

**消费方**：③ `Orchestrator`、`AgentRoomService`

#### IsolatedWorkSpacePort

> 实现方：⑦ | 包：`contracts.workspace`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `create` | `sourcePath` ✓, `sessionId` ✓ | `Workspace` | — | 隔离工作区已创建 | 创建失败→异常 |
| `findByWorkspaceId` | `workspaceId` ✓ | `@Nullable Workspace` | — | 工作区 | — |

**消费方**：③ `AgentRoomService`、`WorkSpaceSessionCoordinator`

#### SessionArchivePort

> 实现方：agent-service | 包：`contracts.runtime`

| 方法 | 入参 | 出参 | 前置 | 后置 | 失败 |
|------|------|------|------|------|------|
| `archive` | `sessionId` ✓ | void | — | 会话已归档 | — |
| `findByTopic` | `keyword` ✓ | `List<SessionArchiveRecord>` | — | 主题匹配的归档 | — |

**消费方**：③ `AlwaysOnRunner`、`SessionArchiver`

---

## 3. DTO 速查表

### orchestration 核心

| 类型 | 字段 |
|------|------|
| `WorkflowRecords.DefinitionView` | `id`, `name`, `description`, `tenantId`, `projectId`, `definition`(JSON graph), `version`, `status`, `createdBy`, `createdAt`, `updatedAt` |
| `WorkflowRecords.InstanceView` | `id`, `definitionId`, `definitionVersion`, `tenantId`, `projectId`, `status`, `currentNodeId`, `context`, `result`, `errorMessage`, `startedAt`, `completedAt` |
| `WorkflowRecords.NodeLogView` | `id`, `instanceId`, `nodeId`, `nodeType`, `status`, `inputData`, `outputData`, `errorMessage`, `startedAt`, `completedAt` |
| `AgentFlowRecords.PlanView` | `id`, `goal`, `tasks`(TaskView), `status`, `errorMessage`, `progress` |
| `AgentFlowRecords.PlanView.TaskView` | `id`, `description`, `dependsOn`, `agentName`, `status`, `result`, `errorMessage`, `retryCount`, `maxRetries` |
| `AgentJobRecord` | `id`, `jobId`, `agentName`, `taskDescription`, `status`, `result`, `errorMessage`, `durationMs`, `priority`, `sseSessionId`, `depth`, `maxDepth` |

### Team 域

| 类型 | 字段 |
|------|------|
| `TeamApiRecords.AgentTeam` | `id`, `teamId`, `tenantId`, `projectId`, `name`, `leaderAgent`, `description`, `status`, `configJson` |
| `TeamApiRecords.TeamMember` | `id`, `teamId`, `agentName`, `role`, `tags` |
| `TeamApiRecords.TeamDetail` | `AgentTeam team`, `List<TeamMember> members` |
| `TeamApiRecords.TeamTagRoute` | `id`, `teamId`, `tag`, `agentName`, `priority` |
| `TeamApiRecords.Collaboration` | `id`, `collabId`, `teamId`, `tenantId`, `projectId`, `sessionId`, `taskSummary`, `status`, `createdAt` |
| `TeamApiRecords.DagNode` | `id`, `nodeId`, `collabId`, `nodeType`, `title`, `status`, `evidence`, `dependsOn`, `sortOrder` |
| `TeamApiRecords.CollaborationDetail` | `Collaboration collaboration`, `List<DagNode> nodes` |
| `TeamApiRecords.BatchResult` | `teamId`, `assignments`(BatchTaskAssignment), `totalTasks`, `memberCount` |
| `TeamObservabilityRecords.Dashboard` | `teamId`, `name`, `status`, `members`(MemberStatus), `totalMembers` |
| `TeamObservabilityRecords.ComparisonResult` | `List<TeamMetrics> teams` |
| `TeamMentionRecord` | `teamName`, `teamId`, `mentionText`, `teamStatus` |

### AlwaysOn 域

| 类型 | 字段 |
|------|------|
| `AlwaysOnRecords.CreateTaskRequest` | `name`, `agentName`, `discoveryHint`, `intervalSec`, `tokenBudgetPerRun`, `tokenBudgetDaily`, `projectId`, `tenantId` |
| `AlwaysOnRecords.Task` | `id`, `taskId`, `tenantId`, `projectId`, `name`, `agentName`, `discoveryHint`, `intervalSec`, `tokenBudgetPerRun`, `tokenBudgetDaily`, `tokensUsedToday`, `budgetDay`, `status`, `nextRunAt` |
| `AlwaysOnRecords.Run` | `id`, `runId`, `taskId`, `status`, `discoverySummary`, `planSummary`, `executionResult`, `reportSummary`, `tokenUsage` |

### DevMap 域

| 类型 | 字段 |
|------|------|
| `DevMapRecords.DevMap` | `agents`(AgentEntry), `skills`(SkillEntry), `workflows`(WorkflowEntry), `activeSessions`(SessionEntry) |
| `DevMapRecords.TaskBoardView` | `workflowInstances`(WorkflowTaskItem), `chatSessions`(ChatSessionItem) |

---

## 4. 接口统计

| 类别 | 接口数 | 方法数 |
|------|--------|--------|
| **§1 上层暴露（D3→②/内部）** | 17 | ~85 |
| **§2 下层消费（D3→④⑤⑥⑧⑨）** | 17 | ~70 |
| **合计** | 34 | ~155 |

---

*本文档为 D3 编排层接口参考；与 gnex-contracts 源码冲突时以源码为准。*
