# AgentOS 控制台视觉重做 · 设计文档

- **日期**: 2026-06-29
- **状态**: 草稿（待用户审阅）
- **范围**: 切片 A 实时仪表盘的**视觉层重制**——把现有手写 CSS 的简陋界面，重做成 C 风格（科技监控型）企业级控制台质感。
- **关系**: 不动切片 A 已有的功能/逻辑/API/事件模型。这是纯视觉升级，对应 vision 文档（A2）阶段 0.1 的体验打磨。

---

## 0. 为什么做

切片 A 功能完成后，前端"看着简陋、没实质内容"。诊断后明确：简陋源于**纯手写基础 CSS、无设计系统**；内容空源于**当前 gateway 未带 API key**（agent 没真跑）。本设计专注解决前者——视觉层重制。后者（真实推理流）靠带 key 运行解决，不在本 spec 范围。

---

## 1. 目标与非目标

### 1.1 目标
1. 建立**设计系统**（配色/字体/间距/状态色令牌），消除手写 CSS 的随意性。
2. 把左右两栏布局升级为**顶栏 + 侧栏 + 主区**三段式（Grafana/Datadog 范式）。
3. 现有 4 组件 + 3 视图用 **Tailwind + 手写组件**重制为 C 风格质感。
4. 补**空状态/加载占位**，消除白板感。

### 1.2 非目标（明确排除）
- 不加新功能/新页面（对话/管理后台留切片 B/C）。
- 不加图表库（无 recharts/d3）。
- 不加审计 hash 链可视化（留切片 C）。
- 不动后端 API / 事件模型 / hooks / api.ts（逻辑层零改）。
- 不做响应式/移动端（桌面优先）。
- 不做主题切换（固定深色）。
- 不做 i18n（沿用中英混排）。

---

## 2. 设计系统（令牌）

### 2.1 配色（深蓝底 + 紫强调 + 灰阶 + 状态语义色）

| 令牌 | 色值 | 用途 |
|------|------|------|
| `bg-base` | `#0f172a` | 页面底色 |
| `bg-panel` | `#1e293b` | 顶栏/侧栏/卡片底 |
| `border` | `#334155` | 所有边框 |
| `accent` | `#a78bfa` | 品牌/进行中/AI 高亮 |
| `text` | `#e2e8f0` | 主文本 |
| `text-muted` | `#94a3b8` | 次要文本 |
| `text-dim` | `#64748b` | 最弱文本（摘要/占位） |

### 2.2 状态语义色

| 状态 | 色 | 语义 |
|------|----|------|
| running | `#a78bfa`（紫） | 进行中 / AI 推理 |
| completed | `#34d399`（绿） | 成功 |
| sanitized | `#f59e0b`（琥珀） | **脱敏专属**——安全卖点高亮锚点 |
| denied | `#ef4444`（红） | 权限拒绝 |
| errored | `#f97316`（橙） | 工具错误 |
| idle | `#64748b`（灰） | 空闲 |

**设计决定**：琥珀色**专留给脱敏 badge**，不与其它状态混用，让"安全卖点"在界面有专属颜色锚点。

### 2.3 字体（双字族）
- **UI**：`system-ui, -apple-system, Segoe UI`（标题/按钮/表单）
- **数据/代码**：`ui-monospace, Menlo, Consolas`（事件/JSON/run_id/时间戳）——用 Tailwind `font-mono`

### 2.4 间距与圆角
- 间距阶：`4 8 12 16 24` px
- 圆角：`3px`（卡片） / `2px`（徽章） / `0`（左边框强调条，保棱角感）

---

## 3. 布局结构（顶栏 + 侧栏 + 主区）

```
┌─────────────────────────────────────────────────────┐
│ 顶栏 48px                                            │
│ ▲AGENTOS · 实时控制台 ····· [● 2 RUNNING][✓ 5 OK][● connected] │
├──────────┬──────────────────────────────────────────┤
│ 侧栏 240px│ 主区 (flex)                               │
│          │                                          │
│ [提交任务] │ run-7c6d47b7  [● RUNNING]   step 2/20·1.2s│
│ (折叠式)  │ ──────────────────────────────────────── │
│          │ 任务原文（斜体引述）                       │
│ 运行列表   │                                          │
│ ● run-7c6d│ ▸ step 0 · think                         │
│ ✓ run-b64a│ ▸ step 1 · think  ◆ phone:mask           │
│ ✕ run-90a3│ ▸ step 2 · ...                           │
└──────────┴──────────────────────────────────────────┘
```

### 3.1 三区职责
- **顶栏 (48px)**：品牌 ▲AGENTOS + 副标题"实时控制台" + 右侧全局状态徽章（running/ok 计数 + WS 连接状态指示）。
- **侧栏 (240px 固定)**：上半=折叠式提交任务表单，下半=运行列表（状态图标 + run_id + 任务摘要 + 选中高亮）。
- **主区 (flex 自适应)**：选中 run 的实时轨迹——header(run_id + 状态徽章 + 步数/耗时) + 任务原文引述 + 事件时间线。

### 3.2 设计决定
- 侧栏**固定 240px**，主区 flex（响应式留后续，非本范围）。
- 提交表单**折叠式**（默认展开，可收起），不抢主区空间。
- 运行列表项带**状态图标**（●紫=running / ✓绿=ok / ✕红=denied）。
- 顶栏导航位预留（为切片 B/C 留扩展点），但本范围不实现导航切换。

---

## 4. 组件设计

### 4.1 StepCard（推理步）
左紫边框（`border-l-2 border-accent`）+ 步号（`▸ step N · think · Xs`）+ thought（斜体 `text-muted`）+ 工具调用结果（`↳` 符号 + 绿色）。

### 4.2 ToolCallCard（按结果三色）
- allowed：左绿边框 + `✓ ALLOWED`
- denied：左红边框 + `✕ DENIED`
- errored：左橙边框 + `⚠ ERRORED`
统一显示工具名 + params JSON。

### 4.3 SanitizeBadge（琥珀专属）
`◆ SANITIZED` 主标签 + 每字段独立药丸（`phone → mask` / `customer_id → hash`...）。每药丸琥珀描边、不含原始值。

### 4.4 EventTimeline（完整事件流）
`run.started` → 多个 `StepCard`（内嵌 ToolCallCard + SanitizeBadge）→ `run.ended`。用左紫边框把多步串联成"推理链"。

### 4.5 新增组件
- **TopBar**：品牌 + 副标题 + 全局状态徽章组（running 计数 / ok 计数 / WS 连接状态点）。
- **StatusBadge**：统一状态徽章（接收 status 字符串，映射到对应色 + 图标），在运行列表/详情 header 复用。

### 4.6 空状态/加载占位
- 未选中运行：`◇ 未选中运行 · 从左侧选一个 run`（居中、`text-dim`）。
- 等待事件：`◉ ◌ ◌ 等待事件… · agent 推理中`（紫色脉冲点）。

---

## 5. 迁移映射

| 现有 | 目标 | 改动 |
|------|------|------|
| `src/index.css` (73行手写) | Tailwind 指令 + `:root` 令牌 | 删除重写 |
| `src/App.tsx` (两栏) | 三栏布局 + TopBar | 重写 |
| `src/views/RunSubmit.tsx` | 折叠式表单（侧栏内） | Tailwind 重制 |
| `src/views/RunList.tsx` | 带状态图标列表项 | Tailwind 重制 |
| `src/views/RunDetail.tsx` | header + 任务原文 + 时间线 | Tailwind 重制 |
| `src/components/StepCard.tsx` | 左紫边框 + thought + 结果 | 重制 |
| `src/components/ToolCallCard.tsx` | 三色分状态 | 重制 |
| `src/components/SanitizeBadge.tsx` | 琥珀药丸组 | 重制 |
| `src/components/EventTimeline.tsx` | 左边框串联 | 重制 |
| `src/hooks/useEventStream.ts` | — | **零改** |
| `src/lib/api.ts` | — | **零改** |
| `src/hooks/__tests__/useEventStream.test.ts` | — | **零改**（保持绿） |

### 5.1 新增文件
- `src/components/TopBar.tsx`
- `src/components/StatusBadge.tsx`
- `tailwind.config.js`（`theme.extend.colors` 扩展 bg-base/accent/status-* 等语义色）
- `postcss.config.js`

---

## 6. 技术决策

- **Tailwind v3**（稳定，文档全；非 v4）。
- **令牌方式**：`tailwind.config.js` 的 `theme.extend.colors` 扩展自定义色，组件用 `bg-bg-base text-accent` 等语义类。少量复杂值（渐变）用 `:root` CSS 变量 + arbitrary value。
- **等宽字体**：用 Tailwind `font-mono` 默认栈。
- **测试策略**：现有 useEventStream 测试保持绿（hooks/api 零改保证）；视觉层无新增单测（靠肉眼 + 构建验证）；可选加 1 个 StatusBadge 的映射单测（status→色/图标）。

---

## 7. 验收标准

1. 打开控制台，视觉呈现 C 风格（深蓝底 + 紫强调 + 棱角分明），不再是白底简陋样。
2. 三栏布局：顶栏（品牌+全局状态徽章）/ 侧栏（折叠表单+运行列表）/ 主区（实时轨迹）。
3. 工具调用按状态三色区分，脱敏 badge 琥珀专属药丸。
4. 空状态/加载有占位，无白板。
5. 现有 useEventStream 测试仍绿；`npm run build` 成功且产物仍输出到 `gateway/web/dist/`；gateway `//go:embed` 仍能打包前端。
6. 逻辑层（hooks/api/事件模型）零改动。

---

## 8. 未决问题（实现计划阶段细化）
- 顶栏全局状态徽章的 running/ok 计数数据源（从 `/api/runs` 轮询聚合 vs 新增统计端点——MVP 用前者）。
- 折叠表单的交互细节（默认展开/收起、动画）。
- 等宽字体在不同 OS 的回退一致性。
