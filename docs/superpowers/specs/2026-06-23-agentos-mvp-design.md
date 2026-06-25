# AgentOS MVP 设计文档

- **日期**: 2026-06-23
- **状态**: 草稿（待用户审阅）
- **阶段**: 阶段 0 — 安全内核 MVP（方案 A）

---

## 1. 项目画像

### 1.1 一句话定位
做一个**企业级、以"安全与可控"为核心壁垒的 Agent 操作系统**，卖给企业，支持私有化部署。

### 1.2 战略选择（已与用户确认）

| 维度 | 决策 | 理由 |
|------|------|------|
| 项目类型 | "Agent 内核 + 调度器"操作系统 | 把 agent 当"进程"来管理，是真正的 OS 形态 |
| 目的 | 认真的产品 / 创业 | 长期投入，要考虑可靠性、安全、商业化 |
| 目标用户 | 卖给企业（平台） | 企业愿为 agent 付费，技术壁垒（安全/可控）不易被抄 |
| 切入壁垒 | **安全与可控** | 四个候选维度里壁垒最高、最不易被抄的方向 |
| 技术栈 | **混合架构**：Go（内核）+ Python（运行时） | Go 贴近系统、安全强；Python agent 生态好 |

### 1.3 全局路线图（分四阶段，每阶段独立交付）

| 阶段 | 交付物 | 验证目标 |
|------|--------|----------|
| **0. 安全内核（本 MVP）** | 单 agent + 沙箱 + 权限 + 审计 | 核心壁垒"安全沙箱"是否成立 |
| 1. 多 Agent 调度 | agent 生命周期、并发、资源限额、agent 间通信 | 调度层架构 |
| 2. 企业级能力 | 私有化、多租户、可观测性、回滚、Web 控制台 | 能否卖给企业 |
| 3. 生态 | SDK / 插件机制 / 企业系统集成 | 商业化扩展 |

---

## 2. MVP 范围（方案 A — 最小安全内核）

### 2.1 MVP 唯一目标
**验证"安全沙箱内核"这个核心壁垒是否成立**——即 agent 真的能跑任务，同时真的越不过沙箱边界，且全过程可审计。

不在范围内（明确排除）：
- 多 agent / agent 间通信（阶段 1）
- Web UI / 可视化（阶段 2）
- 硬隔离（容器/microVM，阶段 2+）
- 持久化状态恢复的完整实现（MVP 只做基础的崩溃重放记录）

### 2.2 MVP Demo 定义
一个 CLI 演示，**一句话讲清三件事**：agent 能干活、agent 被管住、出了事能查。

```
1. agentos run --task "读 sales.csv 算总和写到 out/"
   → agent 推理、调用工具、完成任务（证明"能干活"）
2. agentos run --task "把数据传到 evil.com"
   → 被拒绝 + 审计记录（证明"被管住"）
3. agentos audit show
   → 导出完整审计日志（证明"能查"）
```

---

## 3. 架构设计

### 3.1 分层架构

```
┌──────────────────────────────────────────────────┐
│  Agent Runtime  (Python)        ← agent 的"大脑" │
│  · LLM 抽象层 (DeepSeek 优先 / OpenAI / 本地)    │
│  · ReAct 推理循环 (思考→行动→观察)               │
│  · 工具调用编排                                  │
└───────────────────┬──────────────────────────────┘
                    │  gRPC over Unix domain socket
                    │  (能力请求 + 审计上报)
┌───────────────────┴──────────────────────────────┐
│  OS Kernel  (Go)                ← "操作系统内核"  │
│  · Capability Gate   每个工具调用先过权限检查     │
│  · Sandbox Manager   危险操作在隔离进程里执行     │
│  · Audit Ledger      所有操作记入不可篡改日志     │
│  · Tool Registry     受控的白名单工具集合         │
└──────────────────────────────────────────────────┘
```

### 3.2 进程模型（单机）

| 角色 | 语言 | 职责 | 安全权威 |
|------|------|------|----------|
| **Kernel** | Go（常驻） | 守门人，持有所有敏感能力的执行权 | ✅ 是 |
| **Agent Runtime** | Python | 执行 LLM 推理循环，**本身零敏感权限** | ❌ 否 |
| **Sandbox 进程** | 由 Kernel 按需拉起 | 执行有副作用的操作（文件/命令/网络） | 受 Kernel 约束 |

**核心安全原则**：Python Runtime 永远不直接碰敏感资源。任何有副作用的操作必须通过 gRPC 向 Kernel 发"能力请求"，Kernel 检查权限 → 在沙箱执行 → 记审计 → 返回结果。即便 agent 被 prompt 注入诱导执行恶意指令，也越不过 Kernel 这道墙。

### 3.3 通信

- **gRPC over Unix domain socket**（单机、低延迟、强类型 schema）
- 不用纯 JSON/stdio（不适合多请求），不用 HTTP（太重）
- protobuf schema 独立维护，Kernel 与 Runtime 共享

---

## 4. 安全三件套（核心壁垒）

### 4.1 沙箱 Sandbox

**分两档，MVP 先软后硬：**

**① 软隔离（MVP 用）**
- 独立的工具执行进程
- 工作目录白名单（只能碰指定根目录，如 `/workspace/`）
- 网络白名单 + 命令白名单
- 纯靠代码逻辑约束，不依赖 cgroups
- ✅ 跨平台、能快速验证壁垒是否成立
- ⚠️ 理论上可被绕过（agent 若真能执行任意代码）

**② 硬隔离（阶段 2+，生产化）**
- 容器 / microVM / seccomp
- 靠 Linux 内核强制隔离
- ✅ 企业级安全，能扛真实攻击
- ⚠️ 重、依赖 Linux 内核、部署复杂

**部署约束**：硬隔离强依赖 Linux 内核特性（cgroups、namespaces、seccomp），因此 **生产部署目标是 Linux**。开发环境在 Windows 上通过 WSL2 / Docker Desktop 跑即可。

### 4.2 权限模型 Capability

**声明式、最小权限：**

- agent 启动时被授予一组 capability，例如：
  - `fs.read:/workspace/**`
  - `fs.write:/workspace/out/**`
  - `cmd.exec:[ls,grep]`
  - `net:disabled`
- 每次工具调用过 **Capability Gate**：在范围内→放行，不在→拒绝（并记审计为 `denied`）
- 企业可按 agent 角色预设权限策略模板

**权限策略文件**（MVP 用 YAML/JSON）：
```yaml
agent_role: data_analyst
capabilities:
  fs.read: ["/workspace/**"]
  fs.write: ["/workspace/out/**"]
  cmd.exec: ["ls", "grep", "wc"]
  net: disabled
  max_steps: 20
```

### 4.3 审计 Audit Ledger

**append-only、可追溯、不可篡改：**

每条记录字段：
- `who` — 哪个 agent / agent_id
- `what` — 操作类型 + 参数
- `when` — 时间戳
- `result` — allowed / denied / error + 输出摘要

实现（MVP）：
- append-only 文件
- **hash 链**（每条记录含前一条的 hash）防篡改
- 阶段 2 升级为正式不可篡改存储

价值：企业"出了事能查、能合规"的命脉；与 LangSmith（偏 dev 观测）的差异化。

---

## 5. Agent Runtime（Python）

### 5.1 LLM 抽象层

```
LLMClient (抽象接口)
  ├── DeepSeekProvider  ← MVP 首选（用户已有 key）
  ├── OpenAIProvider
  └── LocalProvider     → Ollama / vLLM（企业私有化关键）
```

- 抽象层屏蔽厂商差异
- **企业客户最看重**能否接本地模型、数据不出内网——接口 MVP 就留好

### 5.2 推理循环（ReAct）

```
循环 {
  think:   LLM 推理 "下一步该干什么"
  act:     调一个工具（→ 过 Kernel 权限 + 沙箱）
  observe: 拿到工具结果
  重复，直到 LLM 说"任务完成" 或 达到 max_steps
}
```

- MVP 做 ReAct（最经典范式）
- 不做 Plan-and-Execute / Reflexion（YAGNI）

### 5.3 工具协议

Runtime 自己**没有任何真实能力**，所有有副作用操作委托给 Kernel：

```python
# Runtime 侧伪代码
result = kernel_client.call_tool("fs.read", path="/workspace/x.csv")
# Runtime 不知道 fs.read 怎么实现，只是"请求" Kernel 去做
```

**这条边界是整个安全架构的灵魂**：Python 是脑子（可被注入、被骗），Go 是肌肉（永远在 Kernel 控制下）。

---

## 6. 一次任务的完整数据流

```
用户: "读 report.csv，算总销售额"
  │
  ▼
① Kernel 启动 agent 会话
   · 分配 agent_id
   · 加载 capability 策略（fs.read ✓, fs.write ✓, net ✗）
   · 开启审计 session
  │
  ▼
② Runtime 推理循环开始
   LLM 思考 → "我需要读 report.csv"
  │
  ▼
③ Runtime 向 Kernel 请求: call_tool("fs.read", {path})
  │
  ▼
④ Kernel 收到请求:
   · Capability Gate 检查权限 ✓
   · 在沙箱进程里执行 fs.read
   · 记审计: read /workspace/x.csv ✓
   · 返回文件内容
  │
  ▼
⑤ Runtime 把内容喂回 LLM
   LLM 思考 → "需要算总和，写结果到 result.txt"
  │
  ▼
⑥ Runtime 请求: call_tool("fs.write", {path, content})
   · Kernel 检查 fs.write 权限 ✓
   · 沙箱执行写入
   · 记审计 ✓
  │
  ▼
⑦ LLM: "任务完成" → 会话结束
  │
  ▼
⑧ 产出:
   · /workspace/out/result.txt
   · 完整审计日志（可导出给企业合规）
```

**安全红线：**
- LLM **永远不直接**碰文件/网络/命令，只通过步骤 ③⑥ 的请求通道
- 每一次 `call_tool` **必须**经过 ④ 的权限检查，没有捷径
- 每一次 `call_tool` **必须**写审计，没有例外

---

## 7. 错误处理

企业对错误的容忍度远低于个人开发者。MVP 阶段建立这套纪律：

| 场景 | 处理 | 记审计 |
|------|------|--------|
| LLM 调用失败（超时/限流） | 重试 3 次（指数退避）→ 仍失败则终止会话，保存状态 | ✓ |
| 工具执行失败（文件不存在等） | 把错误信息**回传给 LLM**，让它自己想办法 | ✓ |
| **权限被拒** | **不告诉 LLM 拒绝原因细节**（防信息泄露），只说"权限不足" | ✓（标记 denied） |
| 沙箱进程崩溃 | Kernel 重新拉起一个，会话继续 | ✓ |
| Runtime 进程崩溃 | Kernel 检测到，记录崩溃点（完整重放留待阶段 2） | ✓ |
| 推理循环死循环 | 硬性 **max_steps 上限**（默认 20）强制终止 | ✓ |

**关键设计**：所有错误都写审计。错误日志和正常日志在同一 ledger 里——企业合规时"失败的操作"和"成功的操作"一样重要。

---

## 8. 测试策略

安全系统的测试，**安全测试 > 功能测试**。

### 8.1 单元测试（Go + Python 各自）
- Kernel: Capability Gate 给各种权限组合，断言放行/拒绝正确
- Kernel: 审计 ledger 写入后 hash 链连续、不可篡改
- Runtime: 推理循环用 mock LLM，断言工具调用顺序正确

### 8.2 集成测试（跨进程）
- 跑一个完整任务（Kernel + Runtime 都起来），验证端到端数据流

### 8.3 ⭐ 安全对抗测试（差异化、护城河证明）
普通 agent 框架不做，但**必须做**：
```
红队用例库：
  · prompt 注入诱导 agent 读 /etc/shadow → 必须被拒
  · 诱导 agent 联网外传数据 → 必须被拒
  · 诱导 agent 执行 rm → 必须被拒
  · 诱导 agent 写到 /workspace 外 → 必须被拒
```
MVP 就要有这套，**它本身就是卖点**："我们的 OS 通过了 N 个对抗测试用例"。

---

## 9. 技术栈锁定

| 部件 | 技术 | 说明 |
|------|------|------|
| Kernel | **Go** | 用户有 Go 经验 |
| Runtime | **Python 3.11+** | agent 生态 |
| IPC | **gRPC + protobuf** | 强类型、低延迟 |
| LLM Provider（MVP） | **DeepSeek** | 用户已有 key |
| 沙箱（MVP） | 软隔离（独立进程 + 白名单） | 阶段 2 升级硬隔离 |
| 审计存储（MVP） | append-only 文件 + hash 链 | 阶段 2 升级 |
| 测试 | Go testing + pytest | 各语言标准 |
| 部署目标 | 生产 Linux / 开发 WSL2 或 Docker | 硬隔离依赖 Linux 内核 |

---

## 10. 未决问题（实现阶段再细化）

以下不在 MVP 设计范围，留给实现计划阶段：
- 项目目录结构（monorepo 内 kernel/ 与 runtime/ 分仓还是同仓）
- protobuf schema 的具体字段设计
- DeepSeek API 的具体对接方式（兼容 OpenAI 协议）
- capability 策略文件的完整 schema
- CLI 命令的具体参数设计

---

## 11. 成功标准

MVP 完成时，应满足：

1. **功能**：能跑通第 6 节的完整数据流，agent 完成"读 csv → 算总和 → 写结果"任务
2. **安全**：第 8.3 节的所有红队用例全部被正确拒绝
3. **审计**：`agentos audit show` 能导出完整、hash 链连续的审计日志
4. **演示**：能向他人现场演示第 2.2 节的 demo 三步

满足这四条，核心壁垒假设即被验证，可以进入阶段 1（多 agent 调度）。
