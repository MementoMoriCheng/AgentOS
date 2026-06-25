import { renderHook } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useEventStream } from "../useEventStream";

describe("useEventStream", () => {
  it("returns empty events when no runID", () => {
    const { result } = renderHook(() => useEventStream(null, () => ({} as WebSocket)));
    expect(result.current).toEqual([]);
  });

  it("mounts and starts empty for a runID", () => {
    // jsdom 无 WebSocket，用注入的 fake 工厂；只验证 hook 可挂载且初始为空
    const fakeFactory = () =>
      ({
        onmessage: null,
        onclose: null,
        close: () => {},
      }) as unknown as WebSocket;
    const { result } = renderHook(() => useEventStream("r1", fakeFactory));
    expect(result.current).toEqual([]);
  });
});
