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
