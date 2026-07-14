# Loop Engineering 落点评估

> **状态**：评估文档（基于代码核实，非设计稿）  
> **范围**：GNEX 2.x — 在 SessionLoop 落地前后，"AI 自我迭代优化"类机制是否值得做、能做哪些  
> **关联**：[SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) · [RUNTIME-EVOLUTION.md](./RUNTIME-EVOLUTION.md) · [INTELLIGENT-ENGINE-LAYER.md](./INTELLIGENT-ENGINE-LAYER.md)  
> **核查日期**：2026-07-03

---

## 0. 背景与立场

### 0.1 概念边界

Loop Engineering 指设计"Generator → Evaluator → Optimizer"的闭环，让 AI 自我迭代优化 Prompt / 轨迹 / 工具选择。**概念本身没错，但难度被严重低估**：

| 风险 | 说明 |
|------|------|
| **优化器幻觉** | LLM 充当 Optimizer 时会幻觉归因（把噪声当根因），在错误方向上越走越远 |
| **评估器偏见** | Evaluator 偏差会导致 reward hacking——系统迎合评估器而非真正提升能力 |
| **调试黑盒** | Generator / Evaluator / Optimizer / 循环控制任一环节出错都表现为整体退化，无法单步调试 |
| **成本失控** | 真实业务场景下，每轮评估可能数十分钟 / 数十美元，无效震荡跑 10 轮即灾难 |

### 0.2 本文档的判断口径

- **优先信任环境信号**（工具调用结果、用户反馈、审批反哺），**警惕 LLM 归因**
- **优先做小 loop**（turn 内、不修改 Agent 定义），**慎做大 loop**（plan 级、Prompt 重写）
- **优先做独立组件**（不依赖未落地的基础设施），**避免在未稳地基上叠功能**

---

## 1. GNEX 当前 loop 现状（代码核实）

> 以下结论基于 2026-07-03 的代码 grep，**非文档转述**。

### 1.1 当前实际运行时

| 组件 | 状态 | 位置 |
|------|------|------|
| `ReActLoop` | ✅ 实现 | `libs/gnex-agent-sdk/.../runtime/ReActLoop.java` |
| `PhasedAgentLoop` | ✅ 实现 | 同上 |
| `FollowUpContinuationLoop` | ✅ 实现（1.0 双循环的"外环"） | 同上 |
| `MessageQueue`（双 Lane：steering / follow-up） | ✅ 实现 | 同上 |
| **`SessionLoop`** | ❌ **未启动**（设计稿） | 文档画饼，代码零命中 |
| **`ReActTurnEngine`** | ❌ **未启动**（设计稿） | 文档画饼，代码零命中 |
| `application.yml` 中 `event-loop` 配置 | ❌ 不存在 | 证实 SessionLoop 未启用 |

→ **当前生产路径是 1.0 双循环**。2.0 SessionLoop 是规划态，[EXEC-SUMMARY](./SESSION-EVENT-LOOP-EXEC-SUMMARY.md) 也将其列为 P1–P2。

### 1.2 Hook 机制（已存在）

| Hook | 状态 | 位置 |
|------|------|------|
| `PreReasoningHook` / `PostReasoningHook` | ✅ 实现 | `ReActTurnLoop` / `ReActLlmInvoker` |
| `postTurnHook` + `checkpoint.saveProgress` | ✅ 实现 | `ReActLoop` / `ReActTurnLifecycle` |
| `AutoMemoryHook`（implements `PostReasoningHook`） | ✅ 实现 | `libs/gnex-agent-sdk/.../memory/AutoMemoryHook.java` |

→ **Turn 内 hook 是真实存在的**，可作为未来 loop 注入点。

### 1.3 关键警告：`QualityGatePort` 名字误导

文档 [SESSION-EVENT-LOOP-OVERVIEW.md §1.4 ⑤](./SESSION-EVENT-LOOP-OVERVIEW.md) 描述 `QualityGatePort` 为"post-turn ReAct 质量门，不达标重跑一轮"。

**代码实际语义完全不同**——`QualityGateService` 做的是：

1. 读 `target/site/jacoco/jacoco.csv` 算代码覆盖率
2. 跑 `SmokeTestRunner` 冒烟测试
3. 查 quarantine 隔离表

**这是 CI/CD 发布门禁**，由 `QualityGateController` 通过 REST `/api/quality/evaluate` 暴露，**与 ReAct 单轮质量、turn 重跑无任何关系**。

> ⚠️ **后续任何"复用 QualityGatePort 做 ReAct loop"的方案都是基于伪前提**。文档需要修正，或者引入独立的 `TurnQualityPort` 与 CI 的 `QualityGatePort` 区分。

### 1.4 AutoMemory 现状

`AutoMemoryHook.afterLlm()` 当前**只做写入**：

- 每个 LLM turn 后，把 `{agentName, turn, toolResults 片段, response 片段}` 拼成 ≤2000 字符的字符串，调 `GnexMemoryService.persist()` 写入 L1
- **不读取**：hook 内无召回逻辑（召回在另外的 MemoryRecall hook）
- **零埋点**：无 `retrievalCount` / `adoptionSignal` / `rejectSignal` 字段
- **无晋升/淘汰**：L0→L1→L2 的迁移策略当前是规则化的，但未发现评估指标采集

→ **AutoMemory 数据采集是真空白**——这是可独立推进的部分（见 §3.2）。

### 1.5 Reflexion 现状

代码零命中。不存在任何"失败 trace → 注入下一轮 context"的机制。

---

## 2. Loop 落点候选评估

### 2.1 五个候选

| # | 落点 | 类型 | 依赖 SessionLoop | 2.x 可行性 |
|---|------|------|:---:|---|
| 1 | AutoMemory 晋升/淘汰（规则版） | 数据采集 + 规则 | ❌ | ✅ 现在可做埋点部分 |
| 2 | Skill Registry 描述自愈 | Prompt 优化 | ❌ | ⚠️ 可做 PoC，但需 Skill 版本化 + A/B 框架前置 |
| 3 | AgentFlow plan-refine | Plan 优化 | ✅ | ❌ SessionLoop 落地后 |
| 4 | ReAct turn-level Reflexion | 反思 loop | ✅ | ❌ SessionLoop 落地后 |
| 5 | InspectorChain 风险等级动态调整 | 治理学习 | ❌（但需重构 InspectorChain） | ⚠️ 3.0 |

### 2.2 评估口径

每个落点用三维度评估：

- **依赖**：是否需要 SessionLoop / Skill 版本化 / 其他未落地组件
- **评估器可靠性**：信号源是否干净（环境信号 vs LLM 归因）
- **回滚成本**：上线后发现错误，能否快速关掉

---

## 3. 推荐路径

### 3.1 不推荐：现在做完整 loop

**理由**：

1. SessionLoop 是 2.0 承重点（[EXEC-SUMMARY](./SESSION-EVENT-LOOP-EXEC-SUMMARY.md) 明确），未启动时做 loop = 在未稳地基上叠功能
2. Reflexion / Plan-refine 的执行载体都是 SessionLoop，**做完扔掉几率高**
3. 当前没有 turn-level 反馈信号源，评估器无处可挂
4. memory 已记录 ReActTurnEngine 6 大实现风险——说明未来包装本身就有大量坑要先填

### 3.2 推荐：仅 AutoMemory 数据埋点可与 SessionLoop 并行

**为什么是唯一推荐**：

- `AutoMemoryHook` 在 PostReasoningHook 链上，**与 SessionLoop 解耦**——SessionLoop 落地后这个 hook 仍然存在
- 埋点字段（retrievalCount / adoptionSignal / rejectSignal）是**未来任何晋升策略的基础数据**，无论 2.x / 3.x 怎么演进都不会浪费
- 不引入 LLM 归因，**规避文章警告的"优化器幻觉"**
- 工程量小（半天到一天），**风险可控**

**埋点设计要点**：

| 字段 | 采集点 | 信号源 |
|------|--------|--------|
| `retrievalCount` | MemoryRecall hook 命中时自增 | 环境信号（确定） |
| `adoptionSignal` | 后续 turn 的 LLM 输出是否引用了该记忆 | 需要语义匹配（弱 LLM 归因，但用作辅助信号可接受） |
| `rejectSignal` | 用户在 feedback 中否定该记忆 | 环境信号（确定） |

**注意**：`adoptionSignal` 的判定方式需要先做 PoC——不能依赖 LLM "判断是否采纳"，否则又落入优化器幻觉陷阱。优先用关键词匹配 / 引用 id 等确定性信号。

### 3.3 SessionLoop 落地后的优先级

SessionLoop Phase 2a/2b 落地、ReActTurnEngine 那 6 大风险解决后，按以下顺序：

| 顺序 | 落点 | 理由 |
|------|------|------|
| 1 | **ReAct turn-level Reflexion** | 紧贴 SessionLoop 让出点；信号源是 turn 失败本身（环境信号）；最大 ROI |
| 2 | **AutoMemory 规则版晋升** | 数据已在埋点里积累；纯规则，无 LLM 归因 |
| 3 | **Skill 自愈 PoC** | 需先有 Skill 版本化框架；A/B 评估窗口跟 SessionLoop 让出点对齐 |
| 4 | **Plan-refine** | ③ 编排层演进，独立 sprint |
| 5 | **Risk 等级学习** | 涉及 ⑥ 治理旁路演进，最复杂 |

### 3.4 永远不推荐

- **自动改写 Agent 系统提示词**——这是产品骨架，不应让 loop 触碰
- **全自动化闭环无人工审核**——半自动 + 关键节点人审更稳

---

## 4. 文档与代码的语义偏差（待修复）

| 偏差点 | 文档描述 | 代码实际 | 建议 |
|--------|---------|---------|------|
| `QualityGatePort` | post-turn ReAct 质量门（OVERVIEW §1.4 ⑤） | CI/CD 覆盖率 + smoke + quarantine 门禁 | 文档修正，或引入独立 `TurnQualityPort` |
| `ReActTurnEngine` | SessionLoop 内的 turn 引擎（EXEC-SUMMARY） | 零代码 | 文档明确标注"规划态"，避免误导 |
| `SessionLoop` | "GNEX 2.0 架构定稿"（EXEC-SUMMARY 标题） | 零代码、application.yml 无配置 | 同上 |

---

## 5. 附录：代码核查清单（2026-07-03）

```
✅ libs/gnex-agent-sdk/src/main/java/com/gnex/agent/runtime/
    ├── ReActLoop.java
    ├── PhasedAgentLoop.java
    ├── ReActTurnLoop.java
    ├── ReActTurnLifecycle.java
    ├── ReActLlmInvoker.java
    ├── FollowUpContinuationLoop.java      ← 1.0 双循环的外环（仍在用）
    ├── MessageQueue.java                  ← 双 Lane：steering / follow-up
    └── AgentRuntime.java

✅ libs/gnex-agent-sdk/src/main/java/com/gnex/agent/memory/
    ├── AutoMemoryHook.java                ← 只写不读，零埋点
    └── GnexMemoryService.java

✅ services/gnex-platform-service/src/main/java/com/gnex/agent/quality/
    ├── QualityGateService.java            ← CI 覆盖率/smoke/quarantine
    ├── QualityGatePortAdapter.java
    ├── QualityGateMode.java               ← PR / RELEASE 等 CI 模式
    └── QualityReport.java

❌ SessionLoop 相关代码：零命中
❌ ReActTurnEngine：零命中
❌ Reflexion / ReflexionNote：零命中
❌ application.yml 中 event-loop 配置：零命中
```

---

## 6. 相关文档

| 文档 | 用途 |
|------|------|
| [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md) | SessionLoop 技术定稿（规划态） |
| [SESSION-EVENT-LOOP-EXEC-SUMMARY.md](./SESSION-EVENT-LOOP-EXEC-SUMMARY.md) | 2.0 实施摘要 |
| [RUNTIME-EVOLUTION.md](./RUNTIME-EVOLUTION.md) | 1.0 → 2.0 演进路线图 |
| [INTELLIGENT-ENGINE-LAYER.md](./INTELLIGENT-ENGINE-LAYER.md) | ④ 运行时层设计 |
| [AGENT-SERVICE-DESIGN.md](./AGENT-SERVICE-DESIGN.md) | v2.0 能力演进 Phase 5–8 |
