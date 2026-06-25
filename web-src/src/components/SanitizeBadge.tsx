// SanitizeBadge 显示脱敏摘要：哪些字段被哪种策略处理。
// 只含字段名+策略，无原始值（Kernel 侧保证）。
export function SanitizeBadge({
  sanitize,
}: {
  sanitize: { field: string; strategy: string }[];
}) {
  if (!sanitize || sanitize.length === 0) return null;
  return (
    <span className="sanitize-badge" title="已脱敏字段（不含原始值）">
      🔒 {sanitize.map((s) => `${s.field}:${s.strategy}`).join(", ")}
    </span>
  );
}
