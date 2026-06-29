// SanitizeBadge：脱敏摘要，琥珀专属色（安全卖点高亮），每字段独立药丸，无原始值。
export function SanitizeBadge({
  sanitize,
}: {
  sanitize: { field: string; strategy: string }[];
}) {
  if (!sanitize || sanitize.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 mt-1">
      <span className="border border-warn/50 bg-warn/10 text-warn px-2 py-0.5 rounded-chip font-mono text-[9px] tracking-wide">
        ◆ SANITIZED
      </span>
      {sanitize.map((s) => (
        <span
          key={s.field}
          className="border border-warn/30 text-warn px-2 py-0.5 rounded-chip font-mono text-[9px]"
        >
          {s.field} → {s.strategy}
        </span>
      ))}
    </div>
  );
}
