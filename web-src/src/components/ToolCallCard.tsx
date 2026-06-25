import type { AgentEvent } from "../lib/api";

// ToolCallCard 渲染一次工具调用事件（called/denied/errored）。
export function ToolCallCard({ ev }: { ev: AgentEvent }) {
  const cls =
    ev.type === "tool.denied" ? "denied" : ev.type === "tool.errored" ? "errored" : "allowed";
  return (
    <div className={`tool-card ${cls}`}>
      <div>
        {ev.type} · <code>{ev.tool}</code>
      </div>
      {ev.params_json && <pre>{ev.params_json}</pre>}
      {ev.result_json && <pre>{ev.result_json}</pre>}
    </div>
  );
}
