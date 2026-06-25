import { useEffect, useState } from "react";
import { listRuns } from "../lib/api";
import type { RunSummary } from "../lib/api";

// RunList 轮询展示所有 run。
export function RunList({
  onSelect,
}: {
  onSelect: (runID: string) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    listRuns().then(setRuns).catch(() => {});
    const t = setInterval(() => listRuns().then(setRuns).catch(() => {}), 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h3>运行列表</h3>
      {runs.length === 0 && <p className="thought">暂无运行</p>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {runs.map((r) => (
          <li
            key={r.run_id}
            className="run-item"
            onClick={() => onSelect(r.run_id)}
            title={r.task}
          >
            [{r.status}] {r.run_id.slice(0, 8)} · {r.task.slice(0, 30)}
          </li>
        ))}
      </ul>
    </div>
  );
}
