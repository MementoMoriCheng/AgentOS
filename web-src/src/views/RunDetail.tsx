import { useEventStream } from "../hooks/useEventStream";
import { EventTimeline } from "../components/EventTimeline";

// RunDetail 订阅选中 run 的实时事件流并渲染时间线。
export function RunDetail({ runID }: { runID: string }) {
  const events = useEventStream(runID);
  return (
    <div>
      <h3>实时轨迹 · {runID.slice(0, 12)}</h3>
      <EventTimeline events={events} />
    </div>
  );
}
