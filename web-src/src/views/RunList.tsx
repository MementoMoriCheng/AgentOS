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
                isActive ? "bg-accent/10 border-l-2 border-accent" : "hover:bg-bg-elevated/30"
              }`}
            >
              <div className="text-[9px] font-mono">
                <span className={iconCls}> </span>
                <span className={isActive ? "text-ink" : "text-ink-muted"}>
                  {r.run_id.slice(0, 12)}
                </span>
              </div>
              <div
                className={`text-[8px] mt-0.5 truncate ${isActive ? "text-ink-muted" : "text-ink-dim"}`}
              >
                {r.task}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
