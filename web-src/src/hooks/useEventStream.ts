import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "../lib/api";

// wsFactory 可注入，便于测试（jsdom 无 WebSocket）。
type WSFactory = (runID: string) => WebSocket;

export const defaultWSFactory: WSFactory = (runID: string) =>
  new WebSocket(`ws://${location.host}/api/events?run_id=${runID}`);

// useEventStream 订阅某个 run 的实时事件流。
export function useEventStream(
  runID: string | null,
  wsFactory: WSFactory = defaultWSFactory
): AgentEvent[] {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runID) return;
    const ws = wsFactory(runID);
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      try {
        const e = JSON.parse(msg.data) as AgentEvent;
        setEvents((prev) => [...prev, e]);
      } catch {
        // 忽略解析失败的消息
      }
    };
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [runID, wsFactory]);

  return events;
}
