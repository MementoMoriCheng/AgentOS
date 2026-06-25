import { useState } from "react";
import { submitRun, listPolicies, listSanitizations } from "../lib/api";

// RunSubmit 提交任务的表单。
export function RunSubmit({
  onSubmitted,
}: {
  onSubmitted: (runID: string) => void;
}) {
  const [task, setTask] = useState("读 sales.csv 算总和写到 out/");
  const [policy, setPolicy] = useState("data_analyst.yaml");
  const [san, setSan] = useState("pii_rules.yaml");
  const [policies, setPolicies] = useState<string[]>([]);
  const [sans, setSans] = useState<string[]>([]);
  const [error, setError] = useState("");

  async function loadOptions() {
    setPolicies(await listPolicies());
    setSans(await listSanitizations());
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (policies.length === 0) await loadOptions();
    try {
      const { run_id } = await submitRun(task, policy, san);
      onSubmitted(run_id);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div>
        <label>任务</label>
        <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={2} cols={50} />
      </div>
      <div>
        <label>策略</label>
        <input value={policy} onChange={(e) => setPolicy(e.target.value)} list="policies" />
        <datalist id="policies">
          {policies.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
      </div>
      <div>
        <label>脱敏规则</label>
        <input value={san} onChange={(e) => setSan(e.target.value)} list="sans" />
        <datalist id="sans">
          {sans.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>
      <button type="submit">提交任务</button>
      {error && <div style={{ color: "#e55" }}>{error}</div>}
    </form>
  );
}
