/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 背景层
        "bg-base": "#0f172a",
        "bg-panel": "#1e293b",
        "bg-elevated": "#334155",
        // 边框
        "line": "#334155",
        // 强调 / 品牌
        "accent": "#a78bfa",
        // 文本
        "ink": "#e2e8f0",
        "ink-muted": "#94a3b8",
        "ink-dim": "#64748b",
        // 状态语义色
        "ok": "#34d399",
        "warn": "#f59e0b", // 琥珀：脱敏专属
        "deny": "#ef4444",
        "err": "#f97316",
      },
      fontFamily: {
        mono: ["ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        card: "3px",
        chip: "2px",
      },
    },
  },
  plugins: [],
};
