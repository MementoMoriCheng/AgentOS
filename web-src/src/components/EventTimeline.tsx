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
