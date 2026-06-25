// API client + 共享类型。
export interface AgentEvent {
  type: string;
  session_id: string;
  run_id: string;
  tool: string;
  params_json: string;
  result_json: string;
  payload_json: string;
  identity: string;
  timestamp: number;
  sanitize: { field: string; strategy: string }[];
}

export interface RunSummary {
  run_id: string;
  session_id: string;
  status: string;
  task: string;
  started_at: string;
}

export async function submitRun(
  task: string,
  policy: string,
  sanitization: string
): Promise<{ run_id: string; session_id: string }> {
  const r = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, policy, sanitization }),
  });
  if (!r.ok) throw new Error(`submit failed: ${r.status}`);
  return r.json();
}

export async function listRuns(): Promise<RunSummary[]> {
  const r = await fetch("/api/runs");
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function listPolicies(): Promise<string[]> {
  const r = await fetch("/api/policies");
  if (!r.ok) throw new Error(`policies failed: ${r.status}`);
  return r.json();
}

export async function listSanitizations(): Promise<string[]> {
  const r = await fetch("/api/sanitizations");
  if (!r.ok) throw new Error(`sanitizations failed: ${r.status}`);
  return r.json();
}
