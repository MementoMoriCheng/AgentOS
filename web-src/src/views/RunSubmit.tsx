import { useState } from "react";
import { submitRun, listPolicies, listSanitizations } from "../lib/api";

// RunSubmit：折叠式提交表单。默认展开，点标题可收起。
export function RunSubmit({ onSubmitted }: { onSubmitted: (runID: string) => void }) {
  const [open, setOpen] = useState(true);
  const [task, setTask] = useState("读 sales.csv 算总和写到 out/");
  const [policy, setPolicy] = useState("data_analyst.yaml");
  const [san, setSan] = useState("pii_rules.yaml");
  const [policies, setPolicies] = useState<string[]>([]);
  const [sans, setSans] = useState<string[]>([]);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (policies.length === 0) {
      setPolicies(await listPolicies());
      setSans(await listSanitizations());
    }
    try {
      const { run_id } = await submitRun(task, policy, san);
      onSubmitted(run_id);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="text-ink-dim text-[10px] uppercase tracking-wider w-full text-left mb-2"
      >
        {open ? "▼ 提交任务" : "▶ 提交任务"}
      </button>
      {open && (
        <form onSubmit={handleSubmit} className="space-y-2">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={2}
            className="w-full bg-bg-base border border-line rounded-card px-1.5 py-1 text-ink-muted font-mono text-[10px] focus:border-accent focus:outline-none"
          />
          <div className="flex gap-1">
            <input
              value={policy}
              onChange={(e) => setPolicy(e.target.value)}
              list="policies"
              className="flex-1 bg-bg-base border border-line rounded-card px-1.5 py-0.5 text-ink-dim font-mono text-[9px]"
            />
            <input
              value={san}
              onChange={(e) => setSan(e.target.value)}
              list="sans"
              className="flex-1 bg-bg-base border border-line rounded-card px-1.5 py-0.5 text-ink-dim font-mono text-[9px]"
            />
          </div>
          <datalist id="policies">
            {policies.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
          <datalist id="sans">
            {sans.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <button
            type="submit"
            className="w-full border border-accent/50 bg-accent/10 text-accent py-1 rounded-card text-[10px] hover:bg-accent/20"
          >
            ▸ RUN
          </button>
          {error && <div className="text-deny text-[10px]">{error}</div>}
        </form>
      )}
    </div>
  );
}
