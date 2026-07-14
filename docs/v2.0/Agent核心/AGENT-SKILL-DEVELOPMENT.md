# GNEX Agent 与 Skill 开发规范

本文说明在 GNEX 中**可注册、可安装、可被 Orchestrator 调用**的 Agent 与 Skill 应如何编写、打包与发布。实现以 `AgentDefinitionParser`、`ClaudeCodeAdapter`、`AgentRegistryService`、`AgentPackageService` 为准。

---

## 1. 概念区分

| 类型 | 作用 | 注册表 | 磁盘位置（默认 `~/.gnex`） | 运行时调用 |
|------|------|--------|------------------------------|------------|
| **Agent** | 带独立系统提示词的子智能体，可被路由或委派执行 | `agent_registry` | `agents/{domain}/{name}.md` | `route_to_agent`（匹配路由）、`Task` / `TaskOutput`（子 Agent 委派） |
| **Skill** | 可复用的任务说明书（Markdown），渐进式加载 | `skill_registry` | `skills/{domain}/{name}/SKILL.md` 或 `skills/{domain}/{name}.md` | 库工具 `Skill`（扫描 `skills-dir`）；召回用 `MemoryRecallHook` 自动注入 |
| **assistant** | 默认 Skill 宿主；独立安装的 Skill 自动归属此 Agent | `agent_registry` | `agents/default/assistant.md` | `route_to_agent` / `Task`（通用 Worker） |

- Agent **可以**在 YAML 中声明 `skills:`，安装时会把对应 Skill 复制到 `skills-dir` 并写入 `skill_registry`。
- 仅有 `SKILL.md`、没有 `.claude/agents/{name}.md` 的包为 **独立 Skill 包**，默认归属内置 Worker **`assistant`**（见 §4.1），可通过 `route_to_agent` 匹配后 `Task` 委派执行。
- 平台另有 **JAVA / PYTHON_HTTP / CLI / MCP** 等可执行 Skill（管理台「技能」模块），与本文 Markdown 包是两条线；本文主要针对 **Claude Code 兼容的 .md / ZIP 包**。

---

## 2. 目录与命名约定

### 2.1 标准包结构（推荐）

```text
my-package/
└── .claude/
    ├── agents/
    │   └── my-agent.md          # Agent 定义（文件名 = name，kebab-case）
    └── skills/
        └── my-skill/
            ├── SKILL.md         # Skill 主文件（frontmatter 中 name 与目录名一致）
            ├── templates/       # 可选：模板
            └── references/      # 可选：参考资料（会整目录复制）
```

也支持：

- **扁平 Skill**：`.claude/skills/my-skill.md`（较少用，与目录形式二选一）
- **ZIP 根目录仅一层包裹**：`my-package.zip` 内若只有单个子目录且含 `.claude/`，会自动识别为安装根
- **单 Skill 目录**：根目录直接放 `SKILL.md`（无 `.claude`），上传后按 Skill 包处理

### 2.2 命名

| 项 | 规范 |
|----|------|
| Agent / Skill 名称 | **kebab-case**，小写、数字、连字符，如 `demo-helper`、`dev-builder` |
| Agent 文件 | `.claude/agents/{name}.md`，`name` 与 frontmatter 中 `name` 一致 |
| Skill 目录 | `.claude/skills/{name}/SKILL.md` |
| 域（domain） | 安装时默认 `default`；多域隔离由安装 API / 管理台指定 |
| 语言 | 正文与注释建议 **简体中文**（与内置包一致） |

### 2.3 工作区路径（配置）

| 配置项 | 环境变量 | 默认 |
|--------|----------|------|
| 工作区根 | `GNEX_WORKSPACE_DIR` | `~/.gnex` |
| Agent 定义 | `gnex.agents-dir` | `{workspace}/agents` |
| Skill 定义 | `gnex.skills-dir` | `{workspace}/skills` |

仓库内 `gnex/.claude/` 为**源码示例**；运行时以安装复制到 `~/.gnex` 后的注册为准。

---

## 3. Markdown 文件格式

### 3.1 通用结构

每个 Agent 或 Skill 主文件均为：

1. **YAML frontmatter**（`---` 包裹，推荐始终保留）
2. **Markdown / XML 风格正文**（作为 system prompt 或 Skill body）

解析器：`AgentDefinitionParser`（简化 YAML，非完整 SnakeYAML）。

### 3.2 Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 推荐 | 注册名；缺省时用文件名（去掉 `.md`） |
| `description` | 推荐 | 一句话描述；用于路由、列表、工具说明 |
| `source` | 可选 | 来源标识，如 `sample`、`claude-code`、`builtin` |
| `domain` | 可选 | 文档用途；安装时以参数为准 |
| `model` | 可选 | 覆盖该 Agent 使用的 LLM（如 `deepseek-v4-flash`） |
| `skills` | 可选 | 列表，依赖的 Skill 名（安装时自动注册并复制） |
| `commands` | 可选 | 列表，兼容 Claude Code commands |
| `routing_hints` | 可选 | 列表，路由关键词（中文场景建议写用户常说的词） |

列表示例（注意列表项以 `- ` 开头，且紧跟在 `skills:` 等键的下一行）：

```yaml
---
name: my-agent
description: "当用户需要 X 时使用；产出 Y。"
source: my-team
model: deepseek-v4-flash
skills:
  - dev-builder
  - code-review
routing_hints:
  - 代码审查
  - review
---
```

**限制（实现层面）：**

- 仅支持上述键及简单 `key: value`、列表；**不支持**嵌套 YAML、多行 `|` 块（复杂结构请放正文）。
- 字符串值若含冒号，请用双引号包裹。
- 无 frontmatter 时，**整文件内容**视为 system prompt，`description` 为空。

### 3.3 Agent 正文建议结构

参考内置 `demo-helper`、`implementer`：

```markdown
<role>
你是……（角色一句话）
</role>

<capabilities>
  - 能做什么
</capabilities>

<constraints>
  - 禁止做什么（不写文件、不执行 Shell 等）
</constraints>

<output_format>
结构化输出要求
</output_format>

<examples>
  （可选）少而精的示例
</examples>
```

原则：

- **职责单一**：一个 Agent 解决一类任务，避免与 Orchestrator 或其它 Agent 重叠。
- **约束写清**：是否允许调工具、是否允许写工作区外路径、是否必须先通过 `Skill` 加载说明后再动手。
- **不要**在正文或 frontmatter 中写真实 API Key、密码、内网未授权地址。

### 3.4 Skill 正文建议结构

参考 `.claude/skills/skill-builder/templates/skill-template.md` 与 `dev-builder/SKILL.md`：

```markdown
---
name: my-skill
description: 何时触发、做什么、交付什么（一句话）
---

[任务]
    …

[依赖检测]
    必需 / 可选依赖与缺失时的行为

[第一性原则]
    …

[工作流程]
    分步说明

[输出风格]
    （推荐）语态与禁止事项
```

| Section 标题 | 必要性 |
|--------------|--------|
| `[任务]` | 必须 |
| `[依赖检测]` | 强烈建议 |
| `[工作流程]` | 必须 |
| `[第一性原则]`、`[输出风格]` | 推荐 |
| 其它如 `[回退策略]`、`[Phase 完成度判断]` | 按领域按需 |

Skill 名与目录名保持一致；主文件必须叫 **`SKILL.md`**（大小写按扫描逻辑为 `SKILL.md`）。

---

## 4. Agent 与 Skill 的关联

```text
my-agent.md
  skills:
    - dev-builder
    - code-review
```

安装 `my-agent` 时系统会：

1. 将 Agent 写入 `agents/{domain}/my-agent.md` 并插入 `agent_registry`
2. 在 `~/.claude/skills` 或包内查找 `dev-builder`、`code-review`，复制到 `skills/{domain}/` 并注册 `skill_registry`
3. 若 Skill 已存在则跳过复制

**Sub-Agent 模式**：在 Agent 的 `skills:` 中只写**一个**主 Skill（如 `implementer` → `dev-builder`），由该 Skill 规定编码流程。

### 4.1 独立 Skill 与 assistant 默认归属

仅含 `SKILL.md`、没有对应 `.claude/agents/{name}.md` 的包为 **独立 Skill 包**。企业场景要求每个 Skill 在 `skill_registry` 中有明确 `owner_agent`；演示场景也常只上传 Skill ZIP。此类 Skill **不** 归属 Orchestrator，而默认归属内置 Worker **`assistant`**。

| 概念 | 说明 |
|------|------|
| **assistant** | 内置通用 Worker，专职承接「只装了 Skill、没装 Agent」的能力；可被 `route_to_agent` 匹配并 `Task` 委派 |
| **Orchestrator** | 聊天主控（Coordinator），负责理解意图与委派，**不是** Skill 的业务归属桶 |
| **owner_agent** | `skill_registry` 列；独立 Skill 安装后值为 `assistant` |
| **skills: 列表** | `assistant.md` frontmatter；与 DB 同步，供路由语料与 Worker 绑定 |

**安装时写入顺序**（同一请求内同步完成，**无需重启服务或刷新页面**）：

1. 复制 Skill 文件到 `skills/{domain}/{name}/`
2. `skill_registry.registerOrUpdate`，`owner_agent = assistant`
3. `applySkillToAgent("assistant", skillName)`，更新 `assistant.md` 的 `skills:`
4. `agentLoader.reload("assistant")`，刷新内存路由缓存

**下一轮聊天**即可：`route_to_agent` 根据 `assistant` 的 description、`routing_hints`、绑定的 skill 名及 `skill_registry.summary` 匹配用户意图 → `MATCH: agent=assistant` → 同轮 `Task` 委派执行。

**不走默认归属的路径**（保持原 `owner_agent`）：

- Agent 包内 `skills:` 引用的 Skill → 归属安装该 Agent 的父 Agent 名
- Agent 能力行（`registerAgentCapabilitySkill`）→ 归属 Agent 自身

若 Skill 需要**专属** Agent（独立路由名、独立 system prompt），包内应同时提供 `.claude/agents/{name}.md`，不要仅上传 `SKILL.md`。

> **实现状态**：本节为已定稿设计；代码落地见仓库内 `assistant` bootstrap、`AgentSkillOwnershipPolicy` 与 V63 migration（实现中或待合并）。

---

## 5. 安装与发布方式

### 5.1 方式对照

| 方式 | 适用场景 |
|------|----------|
| Web **Agent 管理** 上传 ZIP | 第三方包；先安全评估再确认安装 |
| 对话附件上传 ZIP | 同上；或普通归档（非 Agent 包则仅作会话附件） |
| 工具 `install_agents` | Orchestrator / Worker 在对话中安装 |
| CLI `/install <name>` | 从 `~/.claude/agents` 或已存在于 `~/.gnex/agents` 的定义安装 |
| 仓库 `src/main/resources/agents/` | 内置 Agent（如 `security-evaluator`）首次启动引导 |

### 5.2 `install_agents` 用法要点

```text
install_agents(name="demo-helper")                    # 优先 ~/.claude/agents/demo-helper.md，其次 ~/.gnex/agents
install_agents(name="demo-helper", sourcePath="...")  # 见下表
install_agents(name="--all", sourcePath="/path/repo") # 安装该路径下全部 agents + skills
```

| `sourcePath` 指向 | 行为 |
|-------------------|------|
| 单个 `*.md` | 安装为一个 Agent |
| 含 `SKILL.md` 的目录 | **注册 Skill 并归属 assistant**（`owner_agent=assistant`，热绑定 `skills:`；可通过 `route_to_agent` 匹配 assistant 后 `Task` 执行，无需重启） |
| 含 `.claude/agents/` 的仓库根 | 批量安装 agents + skills |
| 空 | 按 name 从 Claude 主目录或 GNEX agents-dir 查找 |

重复安装前建议：`uninstall_agents(name)` 或 `uninstall_agents("skill:skill-name")`。

**禁止**用 Bash/`Write` 直接往 `~/.gnex` 复制来“注册”，应使用 `install_agents`。

### 5.3 ZIP 包规范（上传安装）

| 限制 | 值 |
|------|-----|
| 压缩包大小 | ≤ 50 MB |
| 解压总大小 | ≤ 120 MB |
| 单文件 | ≤ 15 MB |
| 条目数 | ≤ 600 |

**禁止或会被静态标记的内容：**

- 后缀：`.exe`、`.dll`、`.bat`、`.cmd`、`.ps1`、`.vbs`、`.jar`、`.class`、`.so`、`.dylib`
- 文本样本中的硬编码密钥模式（`api_key`、`password`、`token` 等赋值）
- 路径穿越、`..`、绝对路径条目

**安全评估流程：**

1. 上传解压 → 静态扫描 → 调用内置 `security-evaluator` Agent
2. 报告末尾必须有且仅有：`## Verdict` + `APPROVE` | `REJECT` | `NEEDS_REVIEW`
3. `REJECT` 不可安装；`NEEDS_REVIEW` 需人工确认；`APPROVE` 可安装

编写第三方包时，避免在提示词中诱导执行危险 Shell、外传凭证或绕过沙箱。

### 5.4 自行打包 ZIP 示例

```powershell
cd my-package
Compress-Archive -Path .claude -DestinationPath ..\my-agent-pack.zip -Force
```

Linux/macOS：

```bash
cd my-package && zip -r ../my-agent-pack.zip .claude
```

参考样例：`samples/test-agent-package/`、`samples/demo-helper.zip`。

---

## 6. 安全与边界

| 要求 | 说明 |
|------|------|
| 无密钥 | 使用占位符 + 环境变量；GNEX 凭证走 Credential 模块 |
| 无恶意脚本 | 包内不要捆绑可执行二进制；业务脚本放沙箱外由用户显式管理 |
| 工具风险 | `install_agents` 等为高敏操作；Web 端 Agent 包需用户确认安装 |
| 工作区写入 | Agent 不应要求写入项目仓库内 `.claude/`；应通过安装 API 注册 |
| 沙箱执行 | 若 Skill 涉及 `sandbox_exec`，命令路径相对于沙箱根，避免重复 `sandbox/sandbox/` 前缀 |

---

## 7. 质量检查清单

发布前自检：

- [ ] `name`、`description` 准确，名称 kebab-case
- [ ] Agent 与 Skill 目录结构符合第 2 节
- [ ] `skills:` 所列 Skill 在包内存在或已在目标环境安装
- [ ] 正文约束与 GNEX 工具能力一致（能否使用 `Skill`、能否写文件等）
- [ ] 无真实密钥、无 BLOCKER 级脚本后缀
- [ ] ZIP 在测试环境走通：上传 → 评估 → 安装 → `Skill` / `route_to_agent` 验证
- [ ] 卸载重装：`uninstall_agents` 后再次安装无重复脏数据

---

## 8. 内置参考

| 资源 | 路径 |
|------|------|
| 示例 Agent 包 | `samples/test-agent-package/.claude/agents/demo-helper.md` |
| Skill 模板 | `.claude/skills/skill-builder/templates/skill-template.md` |
| Sub-Agent 示例 | `.claude/agents/implementer.md` |
| 开发 Skill 示例 | `.claude/skills/dev-builder/SKILL.md` |
| 安全评估 Agent | `src/main/resources/agents/security-evaluator.md` |

---

## 9. 常见问题

**Q：只写了 `SKILL.md`，为什么不能被 `route_to_agent`？**  
A：路由针对 **Agent 注册表**。需要增加 `.claude/agents/{name}.md`，或在安装时指定正确的 Agent 定义路径。

**Q：管理台能看到 Skill 但 Agent 调不到？**
A：可能仅磁盘扫描（`SkillOnDiskCatalog`）。执行 `install_agents` 写入 `skill_registry` 后，`Skill` 工具与 `MemoryRecallHook` 才会稳定命中。

**Q：修改已安装包内容？**  
A：改源码后重新打包上传，或改 `~/.gnex/agents`、`~/.gnex/skills` 下文件后 `agentLoader.reloadAll()`（服务重启亦可）；Web 安装场景建议走卸载再装。

**Q：frontmatter 里的 `routing_hints` 安装后还有吗？**  
A：解析时支持；经 `AgentDefinitionConverter` 写回磁盘时**当前不写入** `routing_hints`。若依赖路由词，请保留在正文或待平台后续持久化该字段。

**Q：只装了 Skill，没有 Agent，聊天里怎么用？**  
A：Skill 已自动归属 `assistant`。装完后在同一会话直接描述任务即可；Orchestrator 会 `route_to_agent` 匹配 `assistant` 并委派。无需重启后端或刷新页面。

**Q：为什么不用 Orchestrator 作为 Skill 归属？**  
A：Orchestrator 是 Coordinator，沙箱禁止直接执行业务 Skill；企业语义要求 Skill 挂在 Worker Agent 上。`assistant` 是轻量通用 Worker，专接独立 Skill。

**Q：独立 Skill 和组合包里的 Skill 归属有何不同？**  
A：组合包中 Agent 声明的 `skills:` 归属该 Agent；仅含 `SKILL.md` 的包归属 `assistant`。查看 DevMap 或 `skill_registry.owner_agent` 可确认。

**Q：升级后以前 owner_agent 为空的 Skill 怎么办？**  
A：数据库 migration 回填为 `assistant`；服务启动时可选 reconcile，将 `skills:` 列表与 DB 对齐。

---

*文档版本与 GNEX 主分支实现同步；若安装 API 或解析器变更，以源码为准并更新本文。*
