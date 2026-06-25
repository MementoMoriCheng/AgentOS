import type { AgentEvent } from "../lib/api";

// StepCard 渲染一个 ReAct 推理步（thought + tool_calls）。
export function StepCard({ ev }: { ev: AgentEvent }) {
  const p = JSON.parse(ev.payload_json || "{}");
  return (
    <div className="step-card">
      <div>思考 #{p.step_index}</div>
      {p.thought && <div className="thought">{p.thought}</div>}
      {p.tool_calls && (
        <ul>
          {p.tool_calls.map((tc: any, i: number) => (
            <li key={i}>
              <code>{tc.name}</code> {JSON.stringify(tc.args)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
