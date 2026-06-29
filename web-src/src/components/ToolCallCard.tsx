import type { AgentEvent } from "../lib/api";

// ToolCallCard：按结果三色（绿=allowed / 红=denied / 橙=errored）。
const STYLE: Record<string, { border: string; text: string; icon: string; label: string }> = {
  "tool.called": { border: "border-ok", text: "text-ok", icon: "✓", label: "ALLOWED" },
  "tool.denied": { border: "border-deny", text: "text-deny", icon: "✕", label: "DENIED" },
  "tool.errored": { border: "border-err", text: "text-err", icon: "⚠", label: "ERRORED" },
};

export function ToolCallCard({ ev }: { ev: AgentEvent }) {
  const s = STYLE[ev.type] ?? {
    border: "border-line",
    text: "text-ink-muted",
    icon: "○",
    label: ev.type,
  };
  return (
    <div
      className={`border-l-2 ${s.border} border border-line/50 bg-bg-base rounded-card px-2 py-1.5 my-1 font-mono text-[10px]`}
    >
      <div className={s.text}>
        {s.icon} {s.label} <span className="text-ink-muted">·</span>{" "}
        <code className="text-ink">{ev.tool}</code>
      </div>
      {ev.params_json && (
        <pre className="text-ink-dim mt-0.5 whitespace-pre-wrap">{ev.params_json}</pre>
      )}
      {ev.result_json && (
        <pre className="text-ink-dim mt-0.5 whitespace-pre-wrap">{ev.result_json}</pre>
      )}
    </div>
  );
}
