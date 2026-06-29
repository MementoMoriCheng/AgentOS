// TopBar：品牌 + 副标题 + 全局状态徽章（running/ok 计数 + WS 连接状态点）。
export function TopBar({
  runningCount,
  okCount,
  connected,
}: {
  runningCount: number;
  okCount: number;
  connected: boolean;
}) {
  return (
    <header className="h-12 flex items-center gap-4 px-4 bg-bg-panel border-b border-line shrink-0">
      <div className="text-accent font-bold tracking-widest text-sm">▲ AGENTOS</div>
      <div className="text-line">|</div>
      <div className="text-ink-muted text-xs">实时控制台</div>
      <div className="ml-auto flex items-center gap-2">
        {runningCount > 0 && (
          <span className="border border-accent/50 bg-accent/10 text-accent px-2 py-0.5 rounded-chip font-mono text-[10px]">
            ● {runningCount} RUNNING
          </span>
        )}
        <span className="border border-ok/50 bg-ok/10 text-ok px-2 py-0.5 rounded-chip font-mono text-[10px]">
          ✓ {okCount} OK
        </span>
        <span className={`font-mono text-[10px] ${connected ? "text-ok" : "text-ink-dim"}`}>
          ● {connected ? "connected" : "disconnected"}
        </span>
      </div>
    </header>
  );
}
