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
