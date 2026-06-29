import { useEventStream } from "../hooks/useEventStream";
import { EventTimeline } from "../components/EventTimeline";
import type { RunSummary } from "../lib/api";
import { listRuns } from "../lib/api";
import { useEffect, useState } from "react";
import { StatusBadge } from "../components/StatusBadge";

// RunDetail：选中 run 的实时轨迹——header + 任务原文 + 事件时间线。
export function RunDetail({ runID }: { runID: string }) {
  const events = useEventStream(runID);
  const [meta, setMeta] = useState<RunSummary | null>(null);

  useEffect(() => {
    listRuns().then((rs) => {
      const found = rs.find((r) => r.run_id === runID);
      if (found) setMeta(found);
    });
  }, [runID]);

  const endedEvent = [...events].reverse().find((e) => e.type === "run.ended");
  const finalStatus = endedEvent
    ? JSON.parse(endedEvent.payload_json || "{}").termination
    : meta?.status ?? "running";

  return (
    <div className="p-4 overflow-auto h-full">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-ink font-mono text-sm">{runID.slice(0, 16)}</span>
        <StatusBadge status={finalStatus} />
        <span className="text-ink-dim text-[10px] ml-auto">
          {events.filter((e) => e.type === "runtime.step").length} steps
        </span>
      </div>
      {meta?.task && (
        <div className="text-ink-muted text-xs italic border-l-2 border-line pl-2.5 mb-3">
          {meta.task}
        </div>
      )}
      <EventTimeline events={events} />
    </div>
  );
}
