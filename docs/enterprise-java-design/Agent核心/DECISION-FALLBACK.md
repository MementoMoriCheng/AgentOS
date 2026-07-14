# 决策退化路径与可观测性（Decision Fallback & Observability）

> **定位**：GNEX 文档对 agent 五要素（目标 / 状态 / 控制循环 / 外部接口 / 自主决策）的覆盖中，**自主决策**的"正常路径"（ReAct）在 INTELLIGENT-ENGINE-LAYER 已有，但**退化路径**（异常如何降级）和**可观测性**（决策怎么追踪）散落多处。本文集中描述。
>
> **适用范围**：v2.0 的退化路径与可观测性。v2.1+ 的跨节点决策可观测性（distributed trace）单独扩展。
>
> **版本**：v1.0（2026-07-03）

> **⚠️ v1.0 代码对照**：[V1-CODE-REALITY.md](./V1-CODE-REALITY.md) §2——本文档 §4.5 标"未实现"的 decision_trace / 回放工具 / agent_log 表在代码中**均已实现**（DecisionRecorder + EvaluationReplayService + agent_run_event 表）

---

## 0. 为什么要单独立一份文档

**问题现状**：决策退化散落在多份文档的"故障表"里：

| 现有文档 | 涉及决策退化的部分 |
|---------|--------------|
| AGENT-SERVICE-DESIGN §5.3 | DAG 失败处理策略表 |
| SESSION-EVENT-LOOP §1.2 | 故障表（STALLED 重试 / CANCEL） |
| INTELLIGENT-ENGINE-LAYER | ReAct 正常路径 |
| LOOP-ENGINEERING-ASSESSMENT | 可观测性（提到 trace 未落地） |

**没有统一的"决策退化决策树"**——这导致以下问题易被忽视：

- LLM 超时怎么办？重试几次？降级到什么？
- Skill 找不到怎么办？问用户？换 Skill？
- Plan 步骤失败重试几次后升级？
- 子 agent 卡住时父 agent 等多久放弃？
- 事后怎么回放"为什么 agent 决策调了某个工具"？

本文档回答这些问题。

---

## 1. 决策在五要素中的位置

| 要素 | 主文档 |
|------|------|
| 目标 | [GOAL-LIFECYCLE](./GOAL-LIFECYCLE.md) |
| 状态 | [INTELLIGENT-ENGINE-INTERFACES §5](./INTELLIGENT-ENGINE-INTERFACES.md) |
| 控制循环 | [SESSION-EVENT-LOOP](./SESSION-EVENT-LOOP.md) |
| 外部接口 | [AGENT-COMMUNICATION](./AGENT-COMMUNICATION.md) |
| **自主决策** | **本文档（退化 + 可观测性）+ [INTELLIGENT-ENGINE-LAYER](./INTELLIGENT-ENGINE-LAYER.md)（正常 ReAct 路径）** |

---

## 2. 决策的正常路径（复习）

简述 ReAct 决策正常路径作为退化路径的基线：

```
turn 循环：
  1. 感知：从 transcript 看历史 + 当前状态
  2. 思考：LLM 决策"下一步做什么"
     - 选工具（tool selection）
     - 选参数（argument construction）
     - 判断"是否完成"（completion check）
  3. 行动：调用工具 / 给最终答案
  4. 观察：工具返回 / 用户反馈
  5. 回到 1
```

**正常路径假设**：
- LLM 响应 < 30 秒
- 工具存在且可调用
- 工具返回有效
- Plan 步骤可推进

**退化路径 = 任一假设不成立时的处理**。

---

## 3. 退化路径分类

按"哪个环节失败"分四类：

| 类别 | 失败信号 | 默认退化策略 | 升级策略 |
|------|---------|-----------|---------|
| **A. LLM 失败** | 超时 / 拒答 / 格式错 | 重试 2 次（指数退避） | 升级到 §3.A 兜底 |
| **B. 工具调用失败** | Skill 不存在 / 权限拒绝 / 工具超时 | 换等价 Skill 或问用户 | YIELDING 问用户 |
| **C. Plan 步骤失败** | 步骤连续失败 ≥ 3 次 | 修订 Plan（绕过该步骤） | 提议修订 Goal（GOAL-LIFECYCLE §4） |
| **D. 子 agent 卡住** | 子 agent 超过 task-timeout 无响应 | 标 STALLED → 父决策 | 父 agent 重试 / 降级 / 放弃 |

---

## 3.A LLM 失败的退化

### 3.A.1 LLM 失败的子类

| 子类 | 表现 | 退化 |
|------|------|------|
| **超时** | LLM 响应 > 30s（可配） | 重试 2 次（指数退避 1s / 4s）→ 兜底 Skill |
| **拒答（refusal）** | LLM 返回"我不能做这个" | 不重试，直接 YIELDING 问用户 |
| **格式错** | 返回非 JSON / 不符合 tool_call schema | 重试 2 次（增加 prompt 提示）→ 兜底 Skill |
| **配额不足** | API key 配额耗尽 | 立即 YIELDING + 告警 |

### 3.A.2 兜底 Skill（fallback skill）

**兜底 Skill 不是固定一个**——按 LLM 失败类型选：

| LLM 失败类型 | 兜底 Skill | 说明 |
|------------|----------|------|
| 超时 / 格式错 | `builtin:react_simple` | 退化到无工具的纯对话：问用户"我没想到这一步，能否提示一下？" |
| 拒答 | 无 Skill | 直接 YIELDING（用户介入是唯一路径） |
| 配额不足 | 无 Skill | 直接 YIELDING + 告警（运维层处理） |

**兜底 Skill 调用链**：agent service 加载兜底 Skill 配置 → 失败时 SkillLoader 切换 → 新 turn 用兜底 Skill 跑。

### 3.A.3 LLM 失败的可观测性

每次 LLM 失败必须记录到 decision_trace（见 §4）：

```
decision_trace_entry:
  turn_id: 12
  stage: "llm_decision"
  failure_type: "timeout"
  attempt: 2
  fallback: "builtin:react_simple"
  timestamp: ...
```

---

## 3.B 工具调用失败的退化

### 3.B.1 工具失败的子类

| 子类 | 表现 | 退化 |
|------|------|------|
| **Skill 不存在** | LLM 选了一个 skill_id 但 registry 找不到 | 让 LLM 重选（prompt 提示可用 Skill 列表）→ YIELDING |
| **权限拒绝** | InspectorChain 拦截（PermissionInspector / RiskInspector） | 不重试，直接 YIELDING（用户决定是否升级权限） |
| **工具超时** | 工具执行超过该 Skill 的 timeout | 重试 1 次 → 标 STALLED → YIELDING |
| **工具异常** | 工具返回 exception / 5xx | 重试 2 次 → 降级 / 放弃 |

### 3.B.2 等价 Skill 的发现

GNEX Skill Registry 中，Skill 可声明 `equivalent_to` 字段：

```yaml
skill:
  id: "search_code_advanced"
  equivalent_to: "search_code_basic"
  priority: 2  # 优先级低于 basic
```

工具失败时，agent 优先用同 `equivalent_to` 的低优先级 Skill——但**只有 Skill 显式声明等价关系才会用**，不会自己猜"差不多"。

### 3.B.3 工具失败与重试的关系

**重要**：工具失败的重试不计入 Plan 步骤的失败次数（§3.C）——这是不同层级的退化。

- 工具失败 → 工具层退化（本节）
- 工具层退化耗尽 → Plan 步骤失败 → Plan 层退化（§3.C）
- Plan 层退化耗尽 → Goal 修订 / 终止（GOAL-LIFECYCLE §4）

---

## 3.C Plan 步骤失败的退化

### 3.C.1 失败计数

| 概念 | 定义 |
|------|------|
| **Plan 步骤失败** | 某个 Plan 步骤在工具层退化耗尽后仍未达成 acceptance |
| **失败计数** | 该 Plan 步骤连续失败次数（重启 / 重试独立计数） |
| **阈值** | `plan-step-max-failures` 默认 3（可配） |

### 3.C.2 退化决策树

```
Plan 步骤失败 1 次：
  → agent 自主修订 Plan（重试相同步骤 + 调整参数）
Plan 步骤失败 2 次：
  → agent 自主修订 Plan（换路径，跳过该步骤或换等价步骤）
Plan 步骤失败 3 次（达到阈值）：
  → agent 提议修订 Goal（YIELDING 问用户）
  → 用户长时间不响应 → 自主判定 FAILED
```

### 3.C.3 与 GOAL-LIFECYCLE 的衔接

Plan 步骤失败到阈值后的处理见 [GOAL-LIFECYCLE §4](./GOAL-LIFECYCLE.md)——本文档不重复。

---

## 3.D 子 agent 卡住的退化

参考 AGENT-SERVICE-DESIGN §5.3 的 DAG 失败处理策略表，本文档补充**父 agent 的决策时机**：

| 子 agent 状态持续时间 | 父 agent 决策 |
|------------------|-----------|
| < 子 agent task-timeout | 等待（默认行为） |
| = 子 agent task-timeout | 标子 session 为 STALLED，父 agent 决策：等 / 重试 / 降级 / 放弃 |
| > 子 agent task-timeout × 2 | 父 agent 强制取消子 agent（取消不阻塞父） |

**父 agent 决策依据**（写到 LLM prompt 里）：

- 子 agent 在整个 Goal 中的关键性（关键 → 重试；次要 → 降级 / 跳过）
- 已完成的子任务比例（>50% → 不轻易放弃）
- 用户对时间的敏感度（Goal 的 constraints 含 "deadline" → 优先保时间）

---

## 4. 决策可观测性（Decision Observability）

### 4.1 三层可观测性

| 层 | 内容 | 频率 | 存储 |
|----|------|------|------|
| **L1 decision_trace** | 每个 turn 的决策细节（LLM 输入/输出 / 工具调用 / 失败重试） | 每 turn 多条 | transcript_turn 关联（JSONB 字段） |
| **L2 agent_log** | session 级摘要（Plan 修订 / Goal 修订 / 退化触发） | 每事件一条 | PostgreSQL 单独表 |
| **L3 metrics** | 聚合指标（决策成功率 / 平均退化次数 / 工具失败率） | 每分钟聚合 | Prometheus / 类似 |

### 4.2 decision_trace 结构

每个 turn 在 transcript_turn 的 content JSONB 里嵌入 decision_trace：

```json
{
  "turn_id": 12,
  "speaker_kind": "AI",
  "content_kind": "NL",
  "content": "我准备调用 search_code 工具查找 UserService",
  "decision_trace": [
    {
      "stage": "llm_decision",
      "llm_input_tokens": 1234,
      "llm_output": "{ \"tool\": \"search_code\", \"args\": {...} }",
      "duration_ms": 850
    },
    {
      "stage": "tool_call",
      "tool": "search_code",
      "attempt": 1,
      "result": "success",
      "duration_ms": 320
    }
  ],
  "failure_chain": null  // 失败时这里有内容
}
```

失败场景：

```json
{
  "turn_id": 12,
  "decision_trace": [...],
  "failure_chain": [
    { "stage": "llm_decision", "failure_type": "timeout", "attempt": 1 },
    { "stage": "llm_decision", "failure_type": "timeout", "attempt": 2 },
    { "stage": "fallback", "fallback_skill": "builtin:react_simple" }
  ]
}
```

### 4.3 回放（replay）

**回放能力**是 decision_trace 的核心价值——支持：

| 回放类型 | 用途 | 实现 |
|---------|------|------|
| **完整回放** | 调试 / 事后审查 | 按 turn_id 顺序读 decision_trace 重放 |
| **决策点回放** | "如果当时选另一个工具会怎样" | 重放时替换 LLM 输入，跑 what-if |
| **跨 session 对比** | 同类任务决策路径对比 | 按 task 类型聚合多个 session 的 trace |

**回放的前提**：decision_trace 必须包含 LLM 的完整输入（含 transcript 上下文快照）——这会让单条 trace 很大（数十 KB），按 INTELLIGENT-ENGINE-INTERFACES §5.1 的引用化策略处理（大上下文走 d7 引用）。

### 4.4 metrics 指标集

| 指标 | 含义 | 用途 |
|------|------|------|
| `decision_success_rate` | turn 不触发任何退化的比例 | 总体决策质量 |
| `fallback_rate` | turn 触发任意退化的比例 | 退化频率 |
| `llm_timeout_rate` | LLM 超时比例 | 模型质量 / 网络问题 |
| `tool_failure_rate` | 工具失败比例（按 Skill 维度） | Skill 质量定位 |
| `plan_revision_count` | session 内 Plan 修订次数 | Plan 稳定性 |
| `goal_revision_count` | session 内 Goal 修订次数 | Goal 模糊度 |
| `avg_recovery_turns` | 退化发生后到恢复的平均 turn 数 | 系统韧性 |

**指标粒度**：按 tenant_id / agent_name / skill_id 三维度切片。

### 4.5 当前落地状态

> ⚠️ 本表已根据 v1.0 代码核对修订。完整对照见 [V1-CODE-REALITY.md §2](./V1-CODE-REALITY.md#2-文档标未实现实际-v10-已落地状态应上调)。

| 能力 | 落地状态 | v1.0 实现位置 |
|------|--------|------|
| decision_trace 字段 | ✅ **已实现** | `DecisionRecorder`（PostReasoningHook）+ `DecisionAttribution.java:14-115`；写入 `agent_run_event` 表 `event_type='phase', event_name='decision'` |
| agent_log 表 | ✅ **已实现**（等价表 `agent_run_event`） | V27 migration；7 类事件 + `parent_event_id` 自建树；`AgentRunEventService.java:64-138` |
| 回放工具 | ✅ **已实现** | `EvaluationReplayService.java:46-158`：`replay()` 克隆事件到新 session 返回 `TraceDiff`；`compare()` 产出 common/added/removed/modified |
| metrics 导出 | ❌ 未导 | — |
| 兜底 Skill `builtin:react_simple` | 🟡 **agent 级兜底已实现** | `default-worker` 硬编码常量（`AgentLoader.java:84-181`），含完整 ReAct 工具集；缺 Skill 级 fallback 注册 |

**未实现项仅余**：metrics 导出、Skill 级 fallback 注册机制、`equivalent_to` 元数据字段。

LOOP-ENGINEERING-ASSESSMENT 提到的"trace 未落地"已过时——`agent_run_event` 表已承载等价能力。

---

## 5. 退化决策矩阵（速查表）

**"遇到 X 我该怎么做"的速查**：

| 故障现象 | 第一反应 | 第二反应 | 第三反应 |
|---------|--------|--------|--------|
| LLM 超时（首次） | 重试（指数退避） | 重试 2 次都超时 → 兜底 Skill | 兜底也失败 → YIELDING |
| LLM 拒答 | 直接 YIELDING | — | — |
| Skill 不存在 | 让 LLM 重选（提示可用列表） | 仍选错 → YIELDING | — |
| 权限拒绝 | 直接 YIELDING（用户决定升级） | — | — |
| 工具超时（首次） | 重试 1 次 | 仍超时 → STALLED → YIELDING | — |
| 工具异常（5xx） | 重试 2 次 | 仍异常 → 换等价 Skill | 无等价 → 步骤失败 |
| Plan 步骤失败 1 次 | 重试（调参数） | — | — |
| Plan 步骤失败 2 次 | 换路径 | — | — |
| Plan 步骤失败 3 次 | 提议修订 Goal（YIELDING） | 用户不响应 → FAILED | — |
| 子 agent 超时 | 父 agent 决策（等 / 重试 / 降级 / 放弃） | 父决策失败 → 升级到 Plan 步骤失败 | — |

---

## 6. 与现有文档的引用关系

| 本文章节 | 引用源 | 引用方向 |
|---------|------|---------|
| §2 正常路径 | INTELLIGENT-ENGINE-LAYER | 本文档补充退化路径 |
| §3.A.2 兜底 Skill | Skill Registry 设计 | 本文档补充失败时切换 |
| §3.B.1 工具失败 | InspectorChain | 本文档补充权限拒绝后的退化 |
| §3.C Plan 步骤失败 | GOAL-LIFECYCLE §4 | 本文档衔接到 Goal 修订 |
| §3.D 子 agent 卡住 | AGENT-SERVICE-DESIGN §5.3 | 本文档补充父 agent 决策时机 |
| §4 可观测性 | LOOP-ENGINEERING-ASSESSMENT | 本文档补充目标态 |

---

## 7. 待落地项

> ⚠️ 已根据 v1.0 代码核对。`agent_run_event` 表 + `DecisionRecorder` + `EvaluationReplayService` 已落地，原"高优先级"项实际只剩 Skill 级 fallback。

| 待落地项 | 优先级 | 阻塞 |
|---------|------|------|
| ~~decision_trace 字段实现~~ | ~~高~~ | ✅ 已实现（`DecisionRecorder` + `agent_run_event`） |
| **兜底 Skill 注册机制** | 高 | `builtin:react_simple` 未注册（但 `default-worker` agent 级兜底已实现） |
| **Skill `equivalent_to` 字段** | 中 | Skill 元数据未支持；`SkillDistiller.java:82-87` 输出 frontmatter 仅 name+description |
| ~~agent_log 表 + 写入逻辑~~ | ~~中~~ | ✅ 已实现为 `agent_run_event` 表（V27） |
| **metrics 导出（Prometheus）** | 中 | 端点未暴露 |
| ~~回放工具~~ | ~~低~~ | ✅ 已实现（`EvaluationReplayService`） |
| **`plan-step-max-failures` 配置项** | 中 | 配置 schema 未包含 |

---

## 8. 不展开的话题

- **决策的 A/B 测试**（"换 prompt 后决策质量是否变好"）——评测层
- **决策的成本/延迟权衡**（"用 GPT-4 还是 GPT-3.5"）——业务层
- **决策的安全性**（"agent 是否会调危险工具"）——见 InspectorChain
- **跨 session 决策模式学习**（"agent 是否越来越聪明"）——长期演进话题

这些被有意排除——本文档聚焦"单 session 内决策退化与可观测性"。
