import type { AgentEvent } from "../lib/api";
import { StepCard } from "./StepCard";
import { ToolCallCard } from "./ToolCallCard";
import { SanitizeBadge } from "./SanitizeBadge";

// EventTimeline 按时间序渲染一个 run 的完整事件流。
export function EventTimeline({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return <p className="thought">等待事件…</p>;
  }
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div key={i}>
          {e.type === "run.started" && <div>▶ 运行开始：{e.run_id.slice(0, 12)}</div>}
          {e.type === "runtime.step" && <StepCard ev={e} />}
          {e.type.startsWith("tool.") && (
            <div>
              <ToolCallCard ev={e} />
              <SanitizeBadge sanitize={e.sanitize} />
            </div>
          )}
          {e.type === "run.ended" && (
            <div>
              ⏹ 运行结束：
              {JSON.parse(e.payload_json || "{}").termination}
            </div>
          )}
          {e.type === "session.started" && <div className="thought">会话已建立</div>}
          {e.type === "session.ended" && <div className="thought">会话已结束</div>}
          {e.type === "quota.exceeded" && (
            <div className="tool-card errored">⚠ 资源超限</div>
          )}
        </div>
      ))}
    </div>
  );
}
