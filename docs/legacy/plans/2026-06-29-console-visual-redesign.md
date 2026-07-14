# AgentOS 控制台视觉重做 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把切片 A 的实时仪表盘从手写 CSS 简陋界面，重制成 C 风格（科技监控型）企业级控制台：深蓝底 + 紫强调 + 顶栏/侧栏/主区三栏 + Tailwind。

**Architecture:** 纯视觉层重制。逻辑层（hooks/useEventStream、lib/api、事件模型）零改。设计系统用 Tailwind v3 的 `theme.extend.colors` 扩展语义色令牌；组件用 Tailwind 类重写；新增 TopBar/StatusBadge；三栏布局由 App 重组。

**Tech Stack:** React 18 + Vite 5 + TypeScript + Tailwind CSS v3。

**Spec:** `docs/superpowers/specs/2026-06-29-console-visual-redesign.md`

---

## 全局约定

- **工作目录**：`web-src/`（即 `E:\Project\Agent-Project\AgentOS\web-src`）。所有 npm 命令在此目录跑。
- **构建产物**：`npm run build` 输出到 `../gateway/web/dist/`（vite.config.ts 已配，不动）。
- **逻辑层零改**：`src/hooks/`、`src/lib/api.ts` 不碰。`AgentEvent` 类型字段不变（type/session_id/run_id/tool/params_json/result_json/payload_json/sanitize[{field,strategy}]/timestamp）。
- **现有测试**：`src/hooks/__tests__/useEventStream.test.ts` 必须保持绿。
- **commit 粒度**：每个 Task 一次 commit，conventional commits（`style:` / `feat:` / `chore:`）。
- **验证手段**：每个 Task 后 `npm run build` 必须成功；视觉靠 `npm run dev` 肉眼确认（最后 Task 10 集中验）。

---

## 文件结构总览

**新增：**
- `web-src/tailwind.config.js` — Tailwind 配置 + 设计令牌（语义色）
- `web-src/postcss.config.js` — PostCSS（Tailwind + autoprefixer）
- `web-src/src/components/StatusBadge.tsx` — 统一状态徽章（status→色/图标）
- `web-src/src/components/TopBar.tsx` — 顶栏（品牌 + 全局状态徽章 + WS 连接状态）

**重写（Tailwind 重制）：**
- `web-src/src/index.css` — Tailwind 指令 + 少量 `:root` 变量（替换 73 行手写 CSS）
- `web-src/src/App.tsx` — 两栏 → 三栏布局
- `web-src/src/components/SanitizeBadge.tsx` — 琥珀药丸组
- `web-src/src/components/ToolCallCard.tsx` — 三色分状态
- `web-src/src/components/StepCard.tsx` — 左紫边框 + thought + 结果
- `web-src/src/components/EventTimeline.tsx` — 左边框串联 + 空状态占位
- `web-src/src/views/RunSubmit.tsx` — 折叠式表单
- `web-src/src/views/RunList.tsx` — 状态图标列表项
- `web-src/src/views/RunDetail.tsx` — header + 任务原文 + 时间线

**零改：**
- `web-src/src/hooks/useEventStream.ts`
- `web-src/src/lib/api.ts`
- `web-src/src/main.tsx`（仅可能改 import 路径，无逻辑变化）
- `web-src/src/hooks/__tests__/useEventStream.test.ts`

---

## Task 1: 接入 Tailwind + 设计令牌

**Files:**
- Create: `web-src/tailwind.config.js`
- Create: `web-src/postcss.config.js`
- Modify: `web-src/package.json`（加 devDependencies）
- Rewrite: `web-src/src/index.css`

- [ ] **Step 1: 装 Tailwind v3 依赖**

Run（在 `web-src/` 目录）:
```bash
npm install -D tailwindcss@3 postcss autoprefixer
```
Expected: package.json 的 devDependencies 出现 tailwindcss/postcss/autoprefixer。

- [ ] **Step 2: 创建 postcss.config.js**

Create `web-src/postcss.config.js`:
```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 3: 创建 tailwind.config.js（含设计令牌）**

Create `web-src/tailwind.config.js`:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 背景层
        "bg-base": "#0f172a",
        "bg-panel": "#1e293b",
        "bg-elevated": "#334155",
        // 边框
        "line": "#334155",
        // 强调 / 品牌
        "accent": "#a78bfa",
        // 文本
        "ink": "#e2e8f0",
        "ink-muted": "#94a3b8",
        "ink-dim": "#64748b",
        // 状态语义色
        "ok": "#34d399",
        "warn": "#f59e0b",      // 琥珀：脱敏专属
        "deny": "#ef4444",
        "err": "#f97316",
      },
      fontFamily: {
        mono: ['ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        card: '3px',
        chip: '2px',
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 4: 重写 src/index.css（Tailwind 指令 + 基础重置）**

Replace entire content of `web-src/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  height: 100%;
  margin: 0;
}

body {
  @apply bg-bg-base text-ink font-sans;
}

/* 等宽数据块的基础样式（被 font-mono 覆盖时仍保底）*/
pre, code {
  font-family: theme('fontFamily.mono');
}
```

- [ ] **Step 5: 验证构建**

Run（在 `web-src/`）:
```bash
npm run build
```
Expected: 构建成功，产物输出到 `../gateway/web/dist/`。Tailwind 类被编译进 CSS（检查 dist 的 css 文件含 `.bg-bg-base` 之类）。

- [ ] **Step 6: 验证现有测试仍绿**

Run:
```bash
npm test
```
Expected: useEventStream 2 个测试 PASS。

- [ ] **Step 7: Commit**

```bash
git add web-src/package.json web-src/package-lock.json web-src/postcss.config.js web-src/tailwind.config.js web-src/src/index.css
git commit -m "chore(web): integrate Tailwind v3 with design tokens"
```

---

## Task 2: StatusBadge 组件（统一状态徽章）

**Files:**
- Create: `web-src/src/components/StatusBadge.tsx`

被运行列表、详情 header、顶栏复用。输入 status 字符串，输出对应色 + 图标 + 文本。

- [ ] **Step 1: 实现 StatusBadge**

Create `web-src/src/components/StatusBadge.tsx`:
```tsx
// StatusBadge 把 run/tool 的状态映射到 C 风格徽章（色 + 图标 + 大写标签）。
// running=紫 / completed=绿 / crashed/errored=橙 / denied=红 / 其它=灰。

type Status = "running" | "completed" | "crashed" | "errored" | "denied" | string;

const MAP: Record<string, { color: string; icon: string; label: string }> = {
  running: { color: "text-accent border-accent/50 bg-accent/10", icon: "●", label: "RUNNING" },
  completed: { color: "text-ok border-ok/50 bg-ok/10", icon: "✓", label: "COMPLETED" },
  crashed: { color: "text-err border-err/50 bg-err/10", icon: "⚠", label: "CRASHED" },
  errored: { color: "text-err border-err/50 bg-err/10", icon: "⚠", label: "ERRORED" },
  denied: { color: "text-deny border-deny/50 bg-deny/10", icon: "✕", label: "DENIED" },
};

export function StatusBadge({ status }: { status: Status }) {
  const m = MAP[status] ?? { color: "text-ink-dim border-line bg-bg-elevated/30", icon: "○", label: status.toUpperCase() };
  return (
    <span className={`inline-flex items-center gap-1 border px-2 py-0.5 rounded-chip font-mono text-[10px] tracking-wide ${m.color}`}>
      <span>{m.icon}</span>
      <span>{m.label}</span>
    </span>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功（组件无引用方，编译即验证）。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/StatusBadge.tsx
git commit -m "feat(web): add StatusBadge component"
```

---

## Task 3: TopBar 组件（顶栏）

**Files:**
- Create: `web-src/src/components/TopBar.tsx`

品牌 + 副标题 + 全局状态徽章（running/ok 计数 + WS 连接状态）。

- [ ] **Step 1: 实现 TopBar**

Create `web-src/src/components/TopBar.tsx`:
```tsx
// TopBar：品牌 + 副标题 + 全局状态徽章（running/ok 计数 + WS 连接状态点）。
export function TopBar({
  runningCount,
  okCount,
  connected,
}: {
  runningCount: number;
  okCount: number;
  connected: boolean;
}) {
  return (
    <header className="h-12 flex items-center gap-4 px-4 bg-bg-panel border-b border-line shrink-0">
      <div className="text-accent font-bold tracking-widest text-sm">▲ AGENTOS</div>
      <div className="text-line">|</div>
      <div className="text-ink-muted text-xs">实时控制台</div>
      <div className="ml-auto flex items-center gap-2">
        {runningCount > 0 && (
          <span className="border border-accent/50 bg-accent/10 text-accent px-2 py-0.5 rounded-chip font-mono text-[10px]">
            ● {runningCount} RUNNING
          </span>
        )}
        <span className="border border-ok/50 bg-ok/10 text-ok px-2 py-0.5 rounded-chip font-mono text-[10px]">
          ✓ {okCount} OK
        </span>
        <span className={`font-mono text-[10px] ${connected ? "text-ok" : "text-ink-dim"}`}>
          ● {connected ? "connected" : "disconnected"}
        </span>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/TopBar.tsx
git commit -m "feat(web): add TopBar component"
```

---

## Task 4: SanitizeBadge 重制（琥珀药丸组）

**Files:**
- Rewrite: `web-src/src/components/SanitizeBadge.tsx`

把单行文字 `🔒 field:str, ...` 拆成每字段独立琥珀药丸。

- [ ] **Step 1: 重写 SanitizeBadge**

Replace entire content of `web-src/src/components/SanitizeBadge.tsx`:
```tsx
// SanitizeBadge：脱敏摘要，琥珀专属色（安全卖点高亮），每字段独立药丸，无原始值。
export function SanitizeBadge({
  sanitize,
}: {
  sanitize: { field: string; strategy: string }[];
}) {
  if (!sanitize || sanitize.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 mt-1">
      <span className="border border-warn/50 bg-warn/10 text-warn px-2 py-0.5 rounded-chip font-mono text-[9px] tracking-wide">
        ◆ SANITIZED
      </span>
      {sanitize.map((s) => (
        <span
          key={s.field}
          className="border border-warn/30 text-warn px-2 py-0.5 rounded-chip font-mono text-[9px]"
        >
          {s.field} → {s.strategy}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/SanitizeBadge.tsx
git commit -m "style(web): SanitizeBadge as amber per-field pills"
```

---

## Task 5: ToolCallCard 重制（三色分状态）

**Files:**
- Rewrite: `web-src/src/components/ToolCallCard.tsx`

- [ ] **Step 1: 重写 ToolCallCard**

Replace entire content of `web-src/src/components/ToolCallCard.tsx`:
```tsx
import type { AgentEvent } from "../lib/api";

// ToolCallCard：按结果三色（绿=allowed / 红=denied / 橙=errored）。
const STYLE: Record<string, { border: string; text: string; icon: string; label: string }> = {
  "tool.called": { border: "border-ok", text: "text-ok", icon: "✓", label: "ALLOWED" },
  "tool.denied": { border: "border-deny", text: "text-deny", icon: "✕", label: "DENIED" },
  "tool.errored": { border: "border-err", text: "text-err", icon: "⚠", label: "ERRORED" },
};

export function ToolCallCard({ ev }: { ev: AgentEvent }) {
  const s = STYLE[ev.type] ?? { border: "border-line", text: "text-ink-muted", icon: "○", label: ev.type };
  return (
    <div className={`border-l-2 ${s.border} border border-line/50 bg-bg-base rounded-card px-2 py-1.5 my-1 font-mono text-[10px]`}>
      <div className={s.text}>
        {s.icon} {s.label} <span className="text-ink-muted">·</span>{" "}
        <code className="text-ink">{ev.tool}</code>
      </div>
      {ev.params_json && <pre className="text-ink-dim mt-0.5 whitespace-pre-wrap">{ev.params_json}</pre>}
      {ev.result_json && <pre className="text-ink-dim mt-0.5 whitespace-pre-wrap">{ev.result_json}</pre>}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/ToolCallCard.tsx
git commit -m "style(web): ToolCallCard with status colors"
```

---

## Task 6: StepCard 重制（左紫边框 + thought + 结果）

**Files:**
- Rewrite: `web-src/src/components/StepCard.tsx`

- [ ] **Step 1: 重写 StepCard**

Replace entire content of `web-src/src/components/StepCard.tsx`:
```tsx
import type { AgentEvent } from "../lib/api";

// StepCard：左紫边框 + 步号(think) + thought 斜体 + 工具调用列表（name+args）。
export function StepCard({ ev }: { ev: AgentEvent }) {
  const p = JSON.parse(ev.payload_json || "{}");
  return (
    <div className="border-l-2 border-accent pl-2.5 mb-1.5 font-mono text-[10px]">
      <div>
        <span className="text-accent">▸ step {p.step_index}</span>
        <span className="text-ink-dim"> · think</span>
      </div>
      {p.thought && <div className="text-ink-muted italic mt-0.5">{p.thought}</div>}
      {p.tool_calls && (
        <ul className="mt-0.5 space-y-0.5">
          {p.tool_calls.map((tc: any, i: number) => (
            <li key={i} className="text-ink-muted">
              ↳ <code className="text-ok">{tc.name}</code>{" "}
              <span className="text-ink-dim">{JSON.stringify(tc.args)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/StepCard.tsx
git commit -m "style(web): StepCard with purple accent border"
```

---

## Task 7: EventTimeline 重制（左紫边框串联 + 空状态）

**Files:**
- Rewrite: `web-src/src/components/EventTimeline.tsx`

- [ ] **Step 1: 重写 EventTimeline**

Replace entire content of `web-src/src/components/EventTimeline.tsx`:
```tsx
import type { AgentEvent } from "../lib/api";
import { StepCard } from "./StepCard";
import { ToolCallCard } from "./ToolCallCard";
import { SanitizeBadge } from "./SanitizeBadge";

// EventTimeline：完整事件流，左紫边框串联成"推理链"。
export function EventTimeline({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="text-accent tracking-widest text-sm">◉ ◌ ◌</div>
        <div className="text-accent mt-1 text-xs">等待事件…</div>
        <div className="text-ink-dim text-[10px] mt-0.5">agent 推理中</div>
      </div>
    );
  }
  return (
    <div className="font-mono text-[10px] leading-relaxed">
      {events.map((e, i) => (
        <div key={i}>
          {e.type === "run.started" && (
            <div className="text-accent">▶ run.started · {e.run_id.slice(0, 12)}</div>
          )}
          {e.type === "runtime.step" && <StepCard ev={e} />}
          {e.type.startsWith("tool.") && (
            <div className="pl-2.5">
              <ToolCallCard ev={e} />
              <SanitizeBadge sanitize={e.sanitize} />
            </div>
          )}
          {e.type === "run.ended" && (
            <div className="text-ok mt-1">
              ✓ run.ended · {JSON.parse(e.payload_json || "{}").termination}
            </div>
          )}
          {e.type === "session.started" && <div className="text-ink-dim">会话已建立</div>}
          {e.type === "session.ended" && <div className="text-ink-dim">会话已结束</div>}
          {e.type === "quota.exceeded" && (
            <div className="text-err border-l-2 border-err pl-2.5">⚠ 资源超限</div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/components/EventTimeline.tsx
git commit -m "style(web): EventTimeline with purple chain + empty state"
```

---

## Task 8: 三视图重制（RunSubmit 折叠 / RunList 状态图标 / RunDetail header）

**Files:**
- Rewrite: `web-src/src/views/RunSubmit.tsx`
- Rewrite: `web-src/src/views/RunList.tsx`
- Rewrite: `web-src/src/views/RunDetail.tsx`

- [ ] **Step 1: 重写 RunSubmit（折叠式表单）**

Replace entire content of `web-src/src/views/RunSubmit.tsx`:
```tsx
import { useState } from "react";
import { submitRun, listPolicies, listSanitizations } from "../lib/api";

// RunSubmit：折叠式提交表单。默认展开，点标题可收起。
export function RunSubmit({ onSubmitted }: { onSubmitted: (runID: string) => void }) {
  const [open, setOpen] = useState(true);
  const [task, setTask] = useState("读 sales.csv 算总和写到 out/");
  const [policy, setPolicy] = useState("data_analyst.yaml");
  const [san, setSan] = useState("pii_rules.yaml");
  const [policies, setPolicies] = useState<string[]>([]);
  const [sans, setSans] = useState<string[]>([]);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (policies.length === 0) {
      setPolicies(await listPolicies());
      setSans(await listSanitizations());
    }
    try {
      const { run_id } = await submitRun(task, policy, san);
      onSubmitted(run_id);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="text-ink-dim text-[10px] uppercase tracking-wider w-full text-left mb-2"
      >
        {open ? "▼ 提交任务" : "▶ 提交任务"}
      </button>
      {open && (
        <form onSubmit={handleSubmit} className="space-y-2">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={2}
            className="w-full bg-bg-base border border-line rounded-card px-1.5 py-1 text-ink-muted font-mono text-[10px] focus:border-accent focus:outline-none"
          />
          <div className="flex gap-1">
            <input
              value={policy}
              onChange={(e) => setPolicy(e.target.value)}
              list="policies"
              className="flex-1 bg-bg-base border border-line rounded-card px-1.5 py-0.5 text-ink-dim font-mono text-[9px]"
            />
            <input
              value={san}
              onChange={(e) => setSan(e.target.value)}
              list="sans"
              className="flex-1 bg-bg-base border border-line rounded-card px-1.5 py-0.5 text-ink-dim font-mono text-[9px]"
            />
          </div>
          <datalist id="policies">
            {policies.map((p) => <option key={p} value={p} />)}
          </datalist>
          <datalist id="sans">
            {sans.map((s) => <option key={s} value={s} />)}
          </datalist>
          <button
            type="submit"
            className="w-full border border-accent/50 bg-accent/10 text-accent py-1 rounded-card text-[10px] hover:bg-accent/20"
          >
            ▸ RUN
          </button>
          {error && <div className="text-deny text-[10px]">{error}</div>}
        </form>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 重写 RunList（状态图标列表项）**

Replace entire content of `web-src/src/views/RunList.tsx`:
```tsx
import { useEffect, useState } from "react";
import { listRuns } from "../lib/api";
import type { RunSummary } from "../lib/api";

const STATUS_ICON: Record<string, string> = {
  running: "● text-accent",
  ended: "✓ text-ok",
};
const STATUS_FALLBACK = "○ text-ink-dim";

// RunList：运行列表，带状态图标 + run_id + 任务摘要，选中高亮。
export function RunList({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (runID: string) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  useEffect(() => {
    listRuns().then(setRuns).catch(() => {});
    const t = setInterval(() => listRuns().then(setRuns).catch(() => {}), 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="mt-4">
      <div className="text-ink-dim text-[10px] uppercase tracking-wider mb-1.5">运行列表</div>
      {runs.length === 0 && <div className="text-ink-dim text-[10px]">暂无运行</div>}
      <ul className="space-y-1">
        {runs.map((r) => {
          const isActive = r.run_id === selected;
          const iconCls = STATUS_ICON[r.status] ?? STATUS_FALLBACK;
          return (
            <li
              key={r.run_id}
              onClick={() => onSelect(r.run_id)}
              title={r.task}
              className={`px-2 py-1 rounded-card cursor-pointer ${
                isActive
                  ? "bg-accent/10 border-l-2 border-accent"
                  : "hover:bg-bg-elevated/30"
              }`}
            >
              <div className="text-[9px] font-mono">
                <span className={iconCls}> </span>
                <span className={isActive ? "text-ink" : "text-ink-muted"}>
                  {r.run_id.slice(0, 12)}
                </span>
              </div>
              <div className={`text-[8px] mt-0.5 truncate ${isActive ? "text-ink-muted" : "text-ink-dim"}`}>
                {r.task}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: 重写 RunDetail（header + 任务原文 + 时间线）**

Replace entire content of `web-src/src/views/RunDetail.tsx`:
```tsx
import { useEventStream } from "../hooks/useEventStream";
import { EventTimeline } from "../components/EventTimeline";
import type { RunSummary } from "../lib/api";
import { listRuns } from "../lib/api";
import { useEffect, useState } from "react";
import { StatusBadge } from "../components/StatusBadge";

// RunDetail：选中 run 的实时轨迹——header + 任务原文 + 事件时间线。
export function RunDetail({ runID }: { runID: string }) {
  const events = useEventStream(runID);
  const [meta, setMeta] = useState<RunSummary | null>(null);

  useEffect(() => {
    listRuns().then((rs) => {
      const found = rs.find((r) => r.run_id === runID);
      if (found) setMeta(found);
    });
  }, [runID]);

  const endedEvent = [...events].reverse().find((e) => e.type === "run.ended");
  const finalStatus = endedEvent
    ? JSON.parse(endedEvent.payload_json || "{}").termination
    : meta?.status ?? "running";

  return (
    <div className="p-4 overflow-auto h-full">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-ink font-mono text-sm">{runID.slice(0, 16)}</span>
        <StatusBadge status={finalStatus} />
        <span className="text-ink-dim text-[10px] ml-auto">
          {events.filter((e) => e.type === "runtime.step").length} steps
        </span>
      </div>
      {meta?.task && (
        <div className="text-ink-muted text-xs italic border-l-2 border-line pl-2.5 mb-3">
          {meta.task}
        </div>
      )}
      <EventTimeline events={events} />
    </div>
  );
}
```

- [ ] **Step 4: 验证构建**

Run: `npm run build`
Expected: 成功。

- [ ] **Step 5: Commit**

```bash
git add web-src/src/views/
git commit -m "style(web): rewrite RunSubmit/RunList/RunDetail with tailwind"
```

---

## Task 9: App 三栏组装

**Files:**
- Rewrite: `web-src/src/App.tsx`

把 TopBar + 侧栏(RunSubmit+RunList) + 主区(RunDetail 或空状态) 组装成三栏。

- [ ] **Step 1: 重写 App.tsx**

Replace entire content of `web-src/src/App.tsx`:
```tsx
import { useEffect, useState } from "react";
import { TopBar } from "./components/TopBar";
import { RunSubmit } from "./views/RunSubmit";
import { RunList } from "./views/RunList";
import { RunDetail } from "./views/RunDetail";
import { listRuns } from "./lib/api";

export function App() {
  const [selected, setSelected] = useState<string | null>(null);
  const [runningCount, setRunningCount] = useState(0);
  const [okCount, setOkCount] = useState(0);

  // 顶栏统计：从 /api/runs 轮询聚合 running/ok 计数。
  useEffect(() => {
    const update = () =>
      listRuns()
        .then((rs) => {
          setRunningCount(rs.filter((r) => r.status === "running").length);
          setOkCount(rs.filter((r) => r.status === "ended").length);
        })
        .catch(() => {});
    update();
    const t = setInterval(update, 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex flex-col h-full">
      <TopBar runningCount={runningCount} okCount={okCount} connected={true} />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-60 shrink-0 bg-bg-panel border-r border-line p-3 overflow-auto">
          <RunSubmit onSubmitted={setSelected} />
          <RunList selected={selected} onSelect={setSelected} />
        </aside>
        <main className="flex-1 bg-bg-base overflow-hidden">
          {selected ? (
            <RunDetail runID={selected} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-ink-dim text-2xl">◇</div>
              <div className="text-ink-muted mt-1 text-xs">未选中运行</div>
              <div className="text-ink-dim text-[10px] mt-0.5">
                从左侧选一个 run 查看实时轨迹
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建 + 测试**

Run:
```bash
npm run build && npm test
```
Expected: 构建成功；useEventStream 测试 PASS。

- [ ] **Step 3: Commit**

```bash
git add web-src/src/App.tsx
git commit -m "feat(web): assemble 3-column layout (topbar/sidebar/main)"
```

---

## Task 10: 全量验证 + 构建 + embed

- [ ] **Step 1: 全量测试**

Run（在 `web-src/`）:
```bash
npm test
```
Expected: useEventStream 2 测试 PASS。

- [ ] **Step 2: 生产构建**

Run:
```bash
npm run build
```
Expected: 成功，产物输出到 `../gateway/web/dist/`（index.html + assets/*.css + assets/*.js）。

- [ ] **Step 3: 验证 gateway 仍能 embed 前端**

Run（回到项目根 `E:\Project\Agent-Project\AgentOS`）:
```bash
go build ./gateway/...
```
Expected: 编译成功（`//go:embed` 能读到新 dist）。

- [ ] **Step 4: 启动服务肉眼验收**

Run（项目根，两个终端）:
```bash
# 终端1
go run ./kernel/cmd/agentos serve
# 终端2
go run ./gateway/cmd/agentos-gateway --http 127.0.0.1:18080
```
浏览器开 `http://127.0.0.1:18080`，验收：
1. 深蓝底 + 紫强调，C 风格质感（非白底简陋）。
2. 三栏：顶栏(▲AGENTOS + 状态徽章) / 侧栏(折叠表单+运行列表) / 主区。
3. 未选中时主区显示 ◇ 空状态占位。
4. 提交任务后，运行列表出现新 run，选中后右侧显示实时轨迹（即使 crashed 也看到 run.ended 流）。
5. 工具调用三色、脱敏琥珀药丸（若有真实 run）。

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "style(web): finalize C-style console, build verified, embed ok"
```

---

## 完成标准（对应 spec §7）

1. ✅ C 风格视觉（Task 1 令牌 + 各组件重制）
2. ✅ 三栏布局（Task 9）
3. ✅ 工具三色 + 脱敏琥珀药丸（Task 4/5）
4. ✅ 空状态/加载占位（Task 7 + Task 9）
5. ✅ 测试绿 + build + embed（Task 10）
6. ✅ 逻辑层零改（hooks/api 全程未碰）
