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
  const m = MAP[status] ?? {
    color: "text-ink-dim border-line bg-bg-elevated/30",
    icon: "○",
    label: status.toUpperCase(),
  };
  return (
    <span
      className={`inline-flex items-center gap-1 border px-2 py-0.5 rounded-chip font-mono text-[10px] tracking-wide ${m.color}`}
    >
      <span>{m.icon}</span>
      <span>{m.label}</span>
    </span>
  );
}
