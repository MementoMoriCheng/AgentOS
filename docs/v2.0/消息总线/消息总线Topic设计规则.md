# gnex-bus 2 Topic 设计规范

> **定位**: 本文是 gnex-bus 的 Topic 设计准则。它不只是当前 2 的 Topic 清单,更是后续新增 Topic 的准入、命名、寻址、过滤、消费组和演进规范。  
> **边界**: 正文以 bus 契约概念(`topic` / `orderKey` / `filter` / `consumerGroup`)为主。当前底层实现为 RocketMQ,且 **Topic 名 1:1 映射为 RocketMQ Topic**,故 §4 的字符约束为硬规则,新增 Topic 必须同时满足 bus 语义与 RocketMQ 命名校验。

---

## 1. 核心原则

新增 Topic 是架构级变更,不是实现细节。默认先复用已有 Topic + `filter`;只有当消息的业务类别、可靠性、背压、消费模式或治理边界发生本质变化时,才允许新增 Topic。

Topic 设计遵循五条规则:

1. **Topic 按业务类别划分,不按实体划分**  
   Topic 不得包含 tenant、project、agent、session、sandbox 等高基数字段,避免 Topic 数量随业务实体膨胀。

2. **顺序保证由 `orderKey` 表达**  
   需要保序的实体必须进入 `orderKey`。bus 只承诺同一 `orderKey` 内有序,不承诺跨 `orderKey` 全局有序。

3. **子类型优先用 `filter` 表达**  
   同一业务类别内的状态、事件、动作类型优先使用 `filter` 区分。只有 `filter` 无法满足可靠性、背压、消费模式或治理边界时,才新增 Topic。

4. **消费组按角色组织,不按租户组织**  
   默认使用角色级消费组,如 `sched-cg`、`sync-cg`、`verify-cg`。消费组名不得默认携带 tenant,避免租户规模扩大后消费组爆炸。

5. **多租户隔离由信封字段与消费校验保证**  
   `orderKey` 必须包含 tenant,用于路由分散和同租户实体保序;消费者必须校验 `properties.tenantId`。强隔离租户可进一步使用独立消费组、独立集群或基础设施隔离策略。

---

## 2. Topic 类型体系

每个 Topic 必须先归类,再设计字段。类型决定消费模式、背压策略、线程配置和丢失容忍度。

| 类型   | 适用场景                            | 消费模式 | 背压策略              | 是否可丢     |
| ------ | ----------------------------------- | -------- | --------------------- | ------------ |
| 控制类 | 生命周期控制、资源申请、状态驱动    | 异步消费 | 不丢,调用方重试或降级 | 否           |
| 协作类 | Agent 到 Agent 的任务委派和结果返回 | 异步消费 | 不丢,调用方重试或降级 | 否           |
| 事件类 | 运行事件、成本、质量分等物化数据    | 同步订阅 | 可降级采样并告警      | 可按场景降级 |
| 审计类 | 合规审计、安全审计、操作留痕        | 同步订阅 | 不丢,需要归档兜底     | 否           |

新增 Topic 时如果无法归入以上类型,必须先补充类型定义,再新增 Topic。

---

## 3. 当前标准 Topic 清单

标准 Topic 固定为以下 8 个。新增 Topic 必须按 §9 的流程评审后加入本表。

| Topic             | 类型   | 用途                         | 生产者                  | 消费者(角色组)                                | orderKey               |
| ----------------- | ------ | ---------------------------- | ----------------------- | --------------------------------------------- | ---------------------- |
| `sandbox_request` | 控制类 | 沙箱申请指令                 | Agent 引擎              | 沙箱调度器(`sched-cg`)                        | `{tenant}:{sandboxId}` |
| `sandbox_events`  | 控制类 | 沙箱状态变更                 | 沙箱调度器 / Agent 引擎 | Agent 引擎(`agent-cg`)、状态同步器(`sync-cg`) | `{tenant}:{sandboxId}` |
| `agent_events`    | 事件类 | Agent 运行事件和旁路审计事件 | Agent 引擎 / 沙箱       | 状态同步器(`sync-cg`)、校验引擎(`verify-cg`)  | `{tenant}:{sessionId}` |
| `cost_events`     | 事件类 | LLM 调用成本                 | 模型网关                | 状态同步器(`cost-cg`)                         | `{tenant}:{sessionId}` |
| `quality_events`  | 事件类 | 校验质量分                   | 校验引擎                | 状态同步器(`quality-cg`)                      | `{tenant}:{sessionId}` |
| `a2a_delegate`    | 协作类 | 委派子任务                   | Agent 引擎 / A2A 网关   | 目标 Agent 角色组                             | `{tenant}:{sessionId}` |
| `a2a_response`    | 协作类 | 返回执行结果                 | Agent 引擎 / A2A 网关   | 源 Agent 角色组                               | `{tenant}:{sessionId}` |
| `audit_log`       | 审计类 | 审计日志                     | 所有组件                | 状态同步器(`audit-cg`)                        | `{tenant}`             |

说明:

- 上表 Topic 名即 RocketMQ 物理 Topic 名(§4.1),须同步维护于 `StandardTopics` 常量注册表。
- 原语执行 `Action -> Observation` 走 WebSocket 通道,不新增 `actions` / `observations` Topic。
- 原语执行过程需要审计或回放时,以旁路事件写入 `agent_events` 或 `audit_log`;这不是原语执行通道本身。
- 死信、重试队列等属于中间件实现和运维对象,不计入标准业务 Topic。

---

## 4. 命名规范

Topic 名称必须稳定、短、可读,表达业务类别而不是业务实体。

### 4.1 RocketMQ 字符约束（硬规则）

当前 gnex-bus 将 bus Topic **原样**映射为 RocketMQ Topic(无别名转换)。RocketMQ 只允许以下字符:

```text
^[%|a-zA-Z0-9_-]+$
```

即:字母、数字、下划线 `_`、连字符 `-`、`%`、`|`。**点号 `.` 不在允许范围内**,创建或 produce/subscribe 时会报错,例如:

```text
The specified topic: test.test01, contains illegal characters, allowing only ^[%|a-zA-Z0-9_-]+$
```

因此 **domain 与语义段之间一律用下划线 `_` 连接**,不得使用点号 `.`。错误示例:`test.test01`、`sandbox.request`、`a2a.delegate`;正确示例:`test_request`、`sandbox_request`、`a2a_delegate`。

Topic 名长度建议 1–64 字符;避免 RocketMQ 系统保留名(如 `TBW102`、`%RETRY%` 前缀等,见 RocketMQ 官方限制文档)。

### 4.2 语义命名形式

| 类别   | 推荐形式                                     | 示例                                  |
| ------ | -------------------------------------------- | ------------------------------------- |
| 控制类 | `{domain}_request` / `{domain}_events`       | `sandbox_request`, `sandbox_events`   |
| 协作类 | `{domain}_{action}`                          | `a2a_delegate`, `a2a_response`        |
| 事件类 | `{domain}_events`                              | `agent_events`, `cost_events`         |
| 审计类 | `{domain}_log` 或固定审计名                  | `audit_log`                           |

禁止:

- 禁止在 Topic 名中包含 `tenantId`、`projectId`、`agentId`、`sessionId`、`sandboxId`。
- 禁止用 Topic 表达状态子类型,如 `sandbox_ready_events`;应使用 `sandbox_events + filter=SANDBOX_READY`。
- 禁止为单个业务实例、单个 Agent 实例或单个租户创建 Topic。
- 禁止使用点号 `.` 作为 domain 与语义段的分隔符(RocketMQ 不允许)。

---

## 5. orderKey 规范

`orderKey` 是顺序键和路由键。生产者必须显式传入,消费者不传 `orderKey`。

统一格式:

```text
{tenant}:{entity}
```

当前取值:

| Topic                                             | entity                        |
| ------------------------------------------------- | ----------------------------- |
| `sandbox_request` / `sandbox_events`              | `sandboxId`                   |
| `agent_events` / `cost_events` / `quality_events` | `sessionId`                   |
| `a2a_delegate` / `a2a_response`                   | `sessionId`                   |
| `audit_log`                                       | 可省略 entity,使用 `{tenant}` |

规则:

- tenant 必须在第一段,不得省略。
- 同一业务实体需要保序时,必须使用同一个 `orderKey`。
- 不需要实体级保序的审计类消息可使用 `{tenant}`。
- 修改 `orderKey` 格式是破坏性变更,必须按 §10 走兼容性评审。

注意: `orderKey` 不等于物理隔离。不同 tenant 的消息可能在底层实现中共享物理资源;隔离仍需依赖 `properties.tenantId` 校验、权限控制和必要的基础设施隔离。

---

## 6. filter 规范

`filter` 用于表达同一 Topic 内的子类型。它是生产者贴在消息上的标签,消费者可在订阅或消费后使用。

使用规则:

- 控制类若只有单一语义,可以不使用 `filter`。
- 状态类 Topic 应使用 `filter` 表达状态。
- 事件类 Topic 应使用 `filter` 表达事件类型。
- 成本、质量、审计等 Topic 如果当前只有单一语义,可以暂不定义 `filter`;后续新增子类型时优先加 `filter`,不要直接新增 Topic。

**命名规则**:

- filter 值(即 RocketMQ Tag)**一律使用 `UPPER_SNAKE_CASE`**(全大写 + 下划线分词)。
- 理由:(1) 与 Java enum 常量约定一致,filter 值通常对应代码里的 enum;(2) grep / 日志 / RocketMQ dashboard 检索友好(无大小写歧义、子串可搜);(3) 契合 RocketMQ 社区 Tag 惯例。
- 既有 filter 已统一为此风格(见下表)。新增 filter 若不符合 `UPPER_SNAKE_CASE`,准入评审直接打回(§9 / §10.1)。
- v1 遗留的 `MessageBusEventTypes`(PascalCase,如 `AgentStarted`)已被本规则取代;v2 实现须按下表 `UPPER_SNAKE` 值,不得照搬 v1 enum。

当前标准 filter:

| Topic            | filter                | 含义                     |
| ---------------- | --------------------- | ------------------------ |
| `sandbox_events` | `SANDBOX_CREATING`    | 创建中                   |
| `sandbox_events` | `SANDBOX_READY`       | 就绪                     |
| `sandbox_events` | `SANDBOX_IDLE`        | 空闲                     |
| `sandbox_events` | `SANDBOX_HEARTBEAT`   | 心跳                     |
| `sandbox_events` | `SANDBOX_TIMEOUT`     | 超时                     |
| `sandbox_events` | `SANDBOX_DESTROYED`   | 已销毁                   |
| `agent_events`   | `AGENT_STARTED`        | Agent 运行开始           |
| `agent_events`   | `ACTION_DISPATCHED`    | 原语指令已下发的旁路事件 |
| `agent_events`   | `ACTION_EXECUTED`      | 沙箱已执行的旁路事件     |
| `agent_events`   | `OBSERVATION_RETURNED` | 结果已回传的旁路事件     |
| `agent_events`   | `CHECKPOINT_SAVED`     | 检查点已保存             |
| `agent_events`   | `AGENT_FINISHED`       | Agent 运行结束           |
| `agent_events`   | `ERROR_OCCURRED`       | 不可恢复错误             |

新增 filter 必须登记到本节,并说明含义、生产者和典型消费者。

---

## 7. 消费组规范

消费组表达“谁以什么角色消费消息”,不表达租户和业务实例。

当前标准消费组:

| 消费组           | Topic                            | 角色             |
| ---------------- | -------------------------------- | ---------------- |
| `sched-cg`       | `sandbox_request`                | 沙箱调度器       |
| `agent-cg`       | `sandbox_events`                 | Agent 引擎       |
| `sync-cg`        | `sandbox_events`, `agent_events` | 状态同步器       |
| `verify-cg`      | `agent_events`                   | 校验引擎         |
| `cost-cg`        | `cost_events`                    | 成本物化         |
| `quality-cg`     | `quality_events`                 | 质量分物化       |
| `audit-cg`       | `audit_log`                      | 审计物化         |
| `{agentRole}-cg` | `a2a_delegate`, `a2a_response`   | Agent 协作角色组 |

消费方组织规则:

- 多个实例做同一件事时,使用同一个消费组协作分担。
- 多个角色做不同的事时,必须使用不同消费组独立消费。
- `sandbox_events` 的 Agent 等待就绪与状态同步是两件事,必须分别使用 `agent-cg` 和 `sync-cg`。
- `agent_events` 的状态物化与质量校验是两件事,必须分别使用 `sync-cg` 和 `verify-cg`。

### 7.1 目标路由规则

如果一个 Topic 内的消息有明确目标消费者,必须显式定义目标路由字段,不能只靠消费组命名表达。

A2A 消息必须至少包含:

| Topic          | 必填属性                   | 用途           |
| -------------- | -------------------------- | -------------- |
| `a2a_delegate` | `properties.targetAgentId` | 标识目标 Agent |
| `a2a_response` | `properties.sourceAgentId` | 标识源 Agent   |

实现时可以使用订阅过滤或消费后校验,但文档必须说明目标路由字段。否则多个 Agent 消费组订阅同一 Topic 时会形成广播,导致无关消费者收到消息。

---

## 8. 多租户隔离规则

Topic 不带 tenant,消费组默认不带 tenant。多租户隔离由三层机制保证:

1. **信封路由层**  
   `orderKey` 必须以 tenant 开头,用于路由分散和同租户实体保序。

2. **消息属性层**  
   `properties.tenantId` 必填。消费者处理前必须校验租户是否匹配自身上下文或授权范围。

3. **治理和强隔离层**  
   status、死信、订阅查询等治理接口必须通过显式 tenant 参数或 `X-Tenant-Id` 传播租户。强隔离租户可使用独立消费组、独立集群、独立命名空间或其他基础设施隔离策略。

禁止把“消费组名带 tenant”作为默认隔离方案。该方案只允许用于合规强隔离或迁移期例外,并必须在 Topic 注册表中说明原因。

---

## 9. 新增 Topic 准入流程

新增 Topic 必须按以下顺序评审:

1. **判断是否真需要 Topic**  
   先确认现有 Topic + 新 filter 是否能满足需求。

2. **确认业务类别**  
   必须归入控制类、协作类、事件类或审计类。

3. **确认差异边界**  
   说明为什么不能复用已有 Topic:可靠性、背压、消费模式、消息量级、治理边界或权限边界是否不同。

4. **定义寻址字段**  
   明确 `orderKey` 格式、必填 properties、幂等键和目标路由字段。

5. **定义消费关系**  
   明确生产者、消费者、消费组,以及同组协作还是异组独立。

6. **定义演进策略**  
   明确 `schemaVersion`、filter 扩展规则、兼容窗口和回滚方案。

7. **更新文档和实现清单**  
   同步更新本文 §3、§6、§7、`StandardTopics` 常量、架构/开发指南中的配置示例,并确认 Topic 名通过 RocketMQ 字符校验(§4.1)。

只有满足以下至少一项,才允许新增 Topic:

- 新业务大类无法归入现有 Topic。
- 消费模式与现有 Topic 不同。
- 可靠性或背压策略与现有 Topic 不同。
- 消息量级已经影响同 Topic 内其他子类型。
- 有明确的治理、权限、留存或合规边界。

---

## 10. 演进与兼容性

### 10.1 新增 filter

新增 filter 是低成本演进,优先于新增 Topic。要求:

- 生产者开始发送前,先在本文登记 filter。
- 消费者不订阅新 filter 时不得受影响。
- 需要订阅新 filter 的消费者自行升级。

### 10.2 新增 Topic

新增 Topic 是破坏性较高的演进。要求:

- 先完成 §9 准入评审。
- 新旧 Topic 并行期间,生产者可双写或灰度切流。
- 消费者升级完成后,才能下线旧 Topic。
- 监控、告警、死信、回放和权限规则必须同步补齐。

### 10.3 修改 orderKey

修改 `orderKey` 是高风险变更。允许追加更细维度,如 `{tenant}:{entity}:{sub}`;禁止删除 tenant 段或改变既有段的语义。

### 10.4 回放能力

bus 不保证按 `orderKey` 直接查询单个实体的历史消息。单会话回放应优先走状态同步器物化后的存储;若需要从消息系统回放,应按 Topic + 时间窗口重放,再由消费者按 `properties.sessionId` 或 `orderKey` 精筛。

---

## 11. Topic 注册模板

新增或修改 Topic 时,必须补齐以下信息:

```text
Topic:
类型:
业务用途:
生产者:
消费者:
消费组:
同组/异组关系:
orderKey 格式:
必填 properties:
filter 取值:
目标路由字段:
幂等键:
schemaVersion:
是否可丢:
背压策略:
是否支持回放:
监控指标:
告警阈值:
新增原因:
替代方案评估:
兼容/迁移方案:
```

---

## 12. 速查清单

每次新增或修改 Topic 前,必须确认:

- [ ] Topic 名是否符合 RocketMQ 字符约束(§4.1),且未使用点号 `.`?
- [ ] 能否用已有 Topic + filter 解决?
- [ ] Topic 名是否只表达业务类别,不包含高基数字段?
- [ ] Topic 类型是否明确?
- [ ] `orderKey` 是否包含 tenant 和保序实体?
- [ ] `properties.tenantId` 是否必填并由消费者校验?
- [ ] 消费组是否按角色命名,没有默认携带 tenant?
- [ ] 多个消费者是同组协作还是异组独立?
- [ ] 有目标消费者时,是否定义了目标路由字段?
- [ ] 是否定义了 filter、schemaVersion、幂等键和回放策略?
- [ ] 是否同步更新 Topic 清单、配置示例、监控和告警?

---

> **结论**: Topic 只表达稳定的业务类别;`orderKey` 表达租户和保序实体;`filter` 表达子类型;消费组表达消费角色。新增 Topic 必须证明已有 Topic + filter 无法满足需求,并补齐注册表、兼容方案和治理规则。