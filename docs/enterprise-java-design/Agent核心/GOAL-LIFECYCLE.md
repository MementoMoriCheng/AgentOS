# 目标生命周期（Goal Lifecycle）

> **定位**：GNEX 文档对 agent 五要素（目标 / 状态 / 控制循环 / 外部接口 / 自主决策）的覆盖中，**目标**长期散落在多份文档。本文集中描述目标从产生到终止的完整生命周期，作为目标模型的 SSOT。
>
> **适用范围**：GNEX 作为"企业业务 agent 平台"（用户提供意图，平台生成/执行 Plan）的定位。若 GNEX 仅作"通用 agent 编排"（用户自带 Plan），部分章节可降级。
>
> **版本**：v1.0（2026-07-03）

---

## 0. 为什么要单独立一份文档

**问题现状**：目标的产生、演化、终止散落在 4+ 份文档，读者要自己拼凑：

| 现有文档 | 涉及目标的部分 |
|---------|------------|
| SESSION-EVENT-LOOP §1 | session 启动 intent |
| SESSION-EVENT-LOOP §0 | steering 机制（间接影响目标） |
| AGENT-SERVICE-DESIGN §5.3 | DAG 目标分解 |
| AGENT-SERVICE-DESIGN §5.4 | NL2Workflow（意图转流程图） |
| SESSION-EVENT-LOOP 状态机 | COMPLETED / CANCELLED（目标终止语义） |

**没有统一的"目标生命周期"描述**——这导致以下问题易被忽视：

- 用户说"放弃"，session 是 COMPLETED 还是 CANCELLED？
- Plan 无法达成时，agent 是自己修订还是问用户？
- steering 修改了什么——目标本身，还是达成目标的路径？
- 子 agent 的目标和父 agent 的目标是什么关系？

本文档回答这些问题。

---

## 1. 目标在五要素中的位置

| 要素 | 主文档 |
|------|------|
| **目标** | **本文档** |
| 状态 | [INTELLIGENT-ENGINE-INTERFACES §5](./INTELLIGENT-ENGINE-INTERFACES.md) |
| 控制循环 | [SESSION-EVENT-LOOP](./SESSION-EVENT-LOOP.md) |
| 外部接口 | [AGENT-COMMUNICATION](./AGENT-COMMUNICATION.md)、[AGENT-SKILL-DEVELOPMENT](./AGENT-SKILL-DEVELOPMENT.md) |
| 自主决策 | [DECISION-FALLBACK](./DECISION-FALLBACK.md)（决策退化与可观测性） |

**目标的独立性体现在**：
- 状态、决策、循环、接口都会变，**目标在 session 内相对稳定**
- 目标有**独立的载体**（Plan / task），不是从决策推导出的副产品
- 目标**有独立的演化路径**——可被用户 steering 修订、可被 agent 自主修订、可被判定无法达成而终止

---

## 2. 目标模型的三层抽象

```
Intent（用户意图）   ← 用户原话："帮我重构 UserService"
    ↓ 意图解析
Goal（结构化目标）   ← "对 UserService 类做安全重构，保留 API 签名，提升可测试性"
    ↓ 目标分解
Plan（任务计划）     ← [步骤 1: 分析现状, 步骤 2: 设计方案, 步骤 3: 执行重构, ...]
    ↓ 计划执行
Tasks（原子任务）    ← 每个 ReAct turn 处理一个 task
```

**三层抽象的必要性**：

| 层 | 是否结构化 | 是否可演化 | 谁能改 |
|---|---|---|---|
| Intent | 否（自然语言） | 🟡 用户可随时改 | 用户 |
| Goal | 是（结构化描述） | 🟡 可被 agent 提议修订 | 用户确认后 agent 修改 |
| Plan | 是（步骤序列 / DAG） | ✅ 频繁修订 | agent 自主修订 |
| Tasks | 是（原子动作） | ✅ 每秒级变化 | agent 自主 |

**关键设计原则**：
- **Intent 永远以原文保留**——结构化转换不丢弃原始信息（用户原话可能是后续争议的依据）
- **Goal 修改必须留痕**——每次修订记录时间、触发方（用户/agent）、修订前后内容
- **Plan 修改对用户透明**——agent 修订 Plan 不需要用户确认（除非超出 Goal 范围）

---

## 3. 目标产生（Goal Generation）

### 3.1 三种产生路径

| 路径 | 描述 | Plan 来源 | 适用场景 |
|------|------|---------|---------|
| **A. 用户给意图，平台生成 Plan** | NL2Workflow：意图 → LLM 解析 → 静态 DAG → 用户调整 → 保存 | 平台生成（用户可调） | 企业业务 agent（GNEX 主要定位） |
| **B. 用户自带 Plan** | 用户在前端画 DAG，平台执行 | 用户自绘 | agentic workflow 工具 |
| **C. Agent 自主生成 Plan** | Plan-and-Solve / ReAct：agent 收到 intent 后边跑边规划 | agent LLM | 探索式任务、动态任务 |

GNEX 三种路径都支持（见 AGENT-SERVICE-DESIGN §5.3 的静态/动态/混合 DAG），但**路径 A 是默认路径**——这与"企业业务 agent 平台"定位一致。

### 3.2 意图解析（Intent → Goal）

**意图解析是 lossy 的转换**——自然语言到结构化目标必然丢信息。处理原则：

| 原则 | 含义 |
|------|------|
| **原始 intent 保留** | transcript 里永远存用户原话（speaker_kind=USER, content_kind=NL） |
| **Goal 生成可被用户 review** | 路径 A 下，平台生成的 Goal 显式推送给用户确认（YIELDING 状态） |
| **歧义不下推** | 意图解析发现歧义时，不猜测直接做，而是 YIELDING 问用户（参考 SESSION-EVENT-LOOP §0.4 的"YIELDING 语义"） |
| **Goal 含约束** | 不只是"做什么"，还要包含"不做什么"（constraints）和"什么时候算完成"（acceptance） |

**Goal 的建议结构**：

```yaml
goal:
  objective: "对 UserService 类做安全重构"        # 做什么
  constraints:                                     # 不做什么 / 必须满足的硬约束
    - "保留 API 签名不变"
    - "保留 PostgreSQL 兼容性"
    - "不改动公共调用方"
  acceptance:                                      # 什么时候算完成（可验证）
    - "所有现有测试通过"
    - "代码评审通过"
    - "无新的 checkstyle 告警"
  parent_session: null                             # 父目标（子 agent 场景）
  source_intent: "user_msg_id_xxx"                 # 原始 intent 指针
```

### 3.3 目标分解（Goal → Plan）

**Plan 是 Goal 的执行路径**。三种分解方式（与 AGENT-SERVICE-DESIGN §5.3 三种 DAG 对应）：

| 分解方式 | 适用 | 风险 |
|---------|------|------|
| **静态分解**（NL2Workflow 生成 + 用户调整） | 流程稳定、可重现 | 分支不够灵活 |
| **动态分解**（Plan-and-Solve，agent 边跑边规划） | 探索式、语义判断 | 不可预测 |
| **混合分解**（静态骨架 + 节点内动态） | 主干稳定 + 分支灵活 | 设计复杂 |

**分解的硬约束**：
- 每个 Plan 步骤必须可追溯到 Goal 的某个 acceptance 条件——否则是"无目的步骤"
- Plan 的修订不改变 Goal——若 agent 发现需要修改 Goal，必须 YIELDING 问用户

---

## 4. 目标演化（Goal Evolution）

### 4.1 三种演化触发方

| 触发方 | 演化类型 | 流程 |
|-------|---------|------|
| **用户主动** | steering 修订目标 | fireInbound(STEERING) → SessionLoop 暂停当前 Plan → YIELDING 确认新目标 → 重建 Plan |
| **Agent 提议** | Plan 步骤失败需修订目标 | agent 发起 GoalRevisionRequest → YIELDING 问用户 → 用户确认后修订 |
| **Agent 自主** | Plan 内部步骤调整（不改 Goal） | agent 直接修订，不需确认 |

### 4.2 steering 改的是目标还是路径？

这是常见混淆点。**明确区分**：

| steering 内容 | 影响层 | 处理 |
|--------------|------|------|
| "改成用 Strategy 模式" | Plan（路径选择） | agent 直接修订 Plan |
| "时间紧，先做核心 3 个方法就行" | Goal（acceptance 缩减） | YIELDING 确认新 Goal |
| "刚才说的不动，加一条：不能依赖外部服务" | Goal（constraints 增加） | YIELDING 确认新 Goal |
| "/cancel" | Goal（终止） | 走 §5 终止流程 |

**判断标准**：steering 内容若改变 **objective / constraints / acceptance** 任一项，就是 Goal 修订；只改变"如何达成"是 Plan 修订。

### 4.3 子目标的派生

**Agent DAG 场景**（AGENT-SERVICE-DESIGN §5.3）：父 agent 派子 agent 时，子 agent 的 Goal 必须满足：

- **子 Goal 是父 Goal 的子集**——不能超出父 Goal 范围（sub-optimization 不能破坏父目标）
- **子 Goal 的 acceptance 可独立验证**——父 agent 收到子 agent 返回时能判断"够不够好"
- **子 Goal 失败不直接终止父 Goal**——父 agent 决定重试 / 降级 / 升级

子 Goal 的 `parent_session` 字段指向父 session——这构成了目标的**父子链**。

---

## 5. 目标终止（Goal Termination）

### 5.1 四种终止状态

| 终止状态 | 含义 | session 状态 | 触发条件 |
|---------|------|-----------|---------|
| **SUCCESS** | Goal 的所有 acceptance 满足 | COMPLETED | agent 验证 acceptance 全通过 |
| **PARTIAL_SUCCESS** | 部分 acceptance 满足，agent 判断"够用" | COMPLETED（带 metadata） | agent 主动判断（如 3/5 测试通过且失败的是非关键的） |
| **ABANDONED** | 用户主动放弃 | CANCELLED | 用户 /cancel 或长时间无响应 |
| **FAILED** | Goal 无法达成且无降级路径 | CANCELLED（带 fail_reason） | agent 自主判定（如关键资源不可用、acceptance 永远无法满足） |

### 5.2 关键语义澄清：COMPLETED vs CANCELLED

**这是文档一直没说清的点**。明确如下：

| 状态 | 是否成功 | 是否记入"完成统计" | 是否触发后续自动化（DAG 下游） |
|------|--------|---------------|----------------|
| SUCCESS（→ COMPLETED） | ✅ | ✅ 计入 | ✅ 触发 |
| PARTIAL_SUCCESS（→ COMPLETED） | 🟡 部分 | 🟡 计入但带标记 | 🟡 由下游配置决定是否触发 |
| ABANDONED（→ CANCELLED） | ❌ | ❌ | ❌ 不触发 |
| FAILED（→ CANCELLED） | ❌ | ❌ | ❌ 不触发（除非父 agent 决定降级） |

**判定规则**：用户主动放弃 = CANCELLED（无论 Goal 进度如何）；agent 主动结束 = COMPLETED（无论是否完美）。

### 5.3 "用户切到别的 session / 关页" 怎么算？

参考 SESSION-EVENT-LOOP §1.2 的故障表——**不是终止**：

- session 继续跑直到 SUCCESS / FAILED
- 用户回切可看进度
- 仅当租约过期才走 FAILED（CANCELLED with fail_reason=lease_expired）

这与"用户主动 /cancel"语义不同——切走 ≠ 放弃。

### 5.4 终止时的副作用

| 状态 | 副作用 |
|------|------|
| SUCCESS | 触发 DAG 下游；写 Goal achievement 记录；释放资源 |
| PARTIAL_SUCCESS | 同上但带 partial 标记；DAG 下游按配置决定 |
| ABANDONED | 清理半成品（d7 工作区 / 子 session）；保留 transcript 用于事后审查 |
| FAILED | 同 ABANDONED；额外生成 fail_reason 报告；可能触发告警 |

---

## 6. 失败语义的具体例子

### 6.1 场景：用户中途说"放弃"

```
用户：/cancel
系统：
  1. SessionLoop 收到 CANCEL event
  2. 当前 turn 跑完后退出循环
  3. status = CANCELLED
  4. fail_reason = user_abandoned
  5. 不触发 DAG 下游
  6. transcript 保留（含 /cancel 时刻）
  7. d7 工作区保留（用户可能要回看）
```

### 6.2 场景：Plan 步骤反复失败

```
agent 检测到：某 Plan 步骤连续失败 3 次
agent 决策路径：
  1. 重试（已有机制）
  2. 修订 Plan（自主）
  3. 提议修订 Goal（YIELDING 问用户："这个 acceptance 我做不到，是否放宽？"）
  4. 自主判定 FAILED（用户长时间不响应 YIELDING）
```

### 6.3 场景：acceptance 部分达成

```
Plan 跑完，agent 验证：
  - "所有现有测试通过" ✅
  - "代码评审通过" ✅
  - "无新 checkstyle 告警" ❌（有 2 个 minor 告警）

agent 决策：minor 告警是可接受的（业务判断）
→ status = COMPLETED + metadata: partial_acceptance
→ 触发 DAG 下游（如果下游配置允许 partial）
```

---

## 7. 与现有文档的引用关系

| 本文章节 | 引用源 | 引用方向 |
|---------|------|---------|
| §3.1 三种产生路径 | AGENT-SERVICE-DESIGN §5.3 | 本文档补充目标产生层 |
| §3.3 Goal → Plan 分解 | AGENT-SERVICE-DESIGN §5.4（NL2Workflow） | 本文档补充分解后 Goal 与 Plan 的关系 |
| §4.2 steering 修订 | SESSION-EVENT-LOOP §0（steering 机制） | 本文档澄清 steering 改 Goal 还是 Plan |
| §5.2 COMPLETED vs CANCELLED | SESSION-EVENT-LOOP §1（状态机） | 本文档补充语义层判断规则 |
| §5.3 切到别的 session | SESSION-EVENT-LOOP §1.2（故障表） | 本文档补充非终止场景 |
| §6 失败语义例子 | SESSION-EVENT-LOOP §8（不变量） | 本文档补充具体场景 |

**不重复展开**：本文档只做"目标模型"的统一描述，**具体的状态机实现 / steering API / transcript 存储**仍引用原文档。

---

## 8. 待落地项

本文档是 SSOT，但部分概念尚未在代码 / 契约中落地。

> ⚠️ **v1.0 实际状态**（详见 [V1-CODE-REALITY.md](./V1-CODE-REALITY.md)）：Goal 在 v1.0 是 `conversation_session.goal TEXT` **单列字符串**（V35 migration），不是状态机实体。`GoalService.buildGoalPromptBlock` 把字符串包进 `<goal>...</goal>` 注入 system prompt——**每次推理都重新注入**，不是带状态机的持久指令。

| 待落地项 | 优先级 | 阻塞 |
|---------|------|------|
| **Goal 结构化模型**（§3.2 的 yaml 结构） | 高 | 契约层无对应类。v1.0 `conversation_session.goal TEXT` 单列承载，无 objective/constraints/acceptance 分字段 |
| **GoalRevisionRequest 事件** | 中 | steering API 未覆盖 agent 提议修订 |
| **partial_success 元数据** | 中 | session status 枚举未携带 partial 标记 |
| **fail_reason 标准化枚举** | 中 | CANCELLED 状态无 fail_reason 字段 |
| **Goal achievement 记录表** | 低 | 用于跨 session 统计，可后期补 |

这些项不阻塞当前 v2.0 开发——本文档作为目标模型的**目标态**（target state），落地按需推进。

---

## 9. 不展开的话题

以下话题与目标相关但**不在本文档范围**：

- **目标冲突解决**（多 agent 协作时子目标与父目标冲突）——见 AGENT-COMMUNICATION
- **目标的成本/收益权衡**（"目标值得做吗"）——业务层，非平台层
- **目标的 SLA**（"目标多久必须完成"）——见 SESSION-EVENT-LOOP §8 租约
- **目标完成质量评估**（"完成得好不好"）——评测层，后期补

这些被有意排除——本文档聚焦"目标在 session 内的生命周期"，不涉及跨 session / 业务层 / 评测层。
