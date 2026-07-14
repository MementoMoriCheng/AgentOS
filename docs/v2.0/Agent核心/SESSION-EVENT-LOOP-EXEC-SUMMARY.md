# SessionLoop — 技术总监一页摘要

> **完整架构**：[SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md)（§0 导读 + §2 实现）
> **入门导读**：[SESSION-EVENT-LOOP-OVERVIEW.md](./SESSION-EVENT-LOOP-OVERVIEW.md)（给产品业务运维看）
> **2.0 路线图**：[RUNTIME-EVOLUTION.md](./RUNTIME-EVOLUTION.md)
> **状态**：GNEX 2.0 架构定稿，分 Phase 2a/2b 落地

> 本文仅保留**总监决策必需**的 4 节：决策摘要 / 投资风险 / 实施顺序 / 30 秒话术。
> 稳定性 / 可扩展性 / 可运维性 3 张总监视图已与 SSOT §0.3-0.5 重复，**删除**——请直接读 [SESSION-EVENT-LOOP.md §0](./SESSION-EVENT-LOOP.md)。

---

## 决策摘要

| 项 | 内容 |
|----|------|
| **做什么** | 用 **SessionLoop** 替代 1.0 **steering 内环 + follow-up 外环** 双循环 |
| **为什么（2.0 企业生产）** | 统一调度、可恢复、可扩展、可运维——**不是**为降低 LLM 延迟 |
| **不做什么** | 不替换 Orchestrator；不引入 Netty；不要求 72h 单线程 |
| **与 LongRun 关系** | SessionLoop **让出点** = 长任务 **slice 边界**；须配合租约 + DB 状态机 |
| **不变量** | I1 同 session 单 Loop；I2 CANCEL 下 turn 前生效；I3 turnIndex 单调递增；I4 STALLED 超限则 CANCELLED；I5 低优先级不饿死；I6 SSE 断开不改 Run 状态 |
| **类型契约** | TurnResult (REACT_DONE / TOOL_CALL_PENDING / BUDGET_EXHAUSTED / ERROR) → LoopControlDecision 映射见 [SSOT §3.4](./SESSION-EVENT-LOOP.md) |

---

## 投资与风险

| 项 | 评估 |
|----|------|
| **工作量** | Phase 2a Chat + 2b bus，约 **4–6 人周**（含 E2E），ReActTurnEngine 包装可能遇内部耦合 |
| **依赖** | Phase 1 assistant 可并行；生产建议 **PostgreSQL** |
| **不做风险** | 2.0 继续双调度栈，multi-agent / 长任务成本上升 |
| **降级** | `gnex.event-loop.enabled=false` 回退 1.0 |
| **验收 KPI** | 滚动发布零丢 run；steering 类工单下降；inbox 可告警 |

---

## 2.0 推荐实施顺序

```text
P0  assistant Skill 归属 + 权限/审计硬化
P0  LongRun 分片 + 租约 + watchdog（有长任务时）
P1  PostgreSQL 生产库
P1–P2  SessionLoop 2a（Chat）→ 2b（bus）
```

---

## 评审话术（30 秒）

「1.0 为演示够用，但企业生产需要会话调度、消息总线和长任务在同一条规则下运行。SessionLoop 把持久 checkpoint、租约、背压和优先级队列收成一层，SSE 只是观察者，Run 状态在库里，能滚动发布、能 72 小时分片跑。LLM 不会因此更快，但系统会更容易扩展、恢复和运维。」

---

*一页摘要 — 细节与类图见 [SESSION-EVENT-LOOP.md](./SESSION-EVENT-LOOP.md)*
