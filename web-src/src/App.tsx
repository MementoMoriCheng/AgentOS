import { useState } from "react";
import { RunSubmit } from "./views/RunSubmit";
import { RunList } from "./views/RunList";
import { RunDetail } from "./views/RunDetail";

export function App() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="app">
      <div className="panel">
        <h2>AgentOS 控制台</h2>
        <RunSubmit onSubmitted={setSelected} />
        <RunList onSelect={setSelected} />
      </div>
      <div className="panel panel-detail">
        {selected ? (
          <RunDetail runID={selected} />
        ) : (
          <p className="thought">提交任务或从左侧选一个 run 查看实时轨迹</p>
        )}
      </div>
    </div>
  );
}
