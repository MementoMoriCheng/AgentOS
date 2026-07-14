import os
import tempfile
import time

from fastapi.testclient import TestClient

from cp.server.cli import build_app


def _wait_ended(mgr, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = mgr.get(run_id)
        if r is not None and r.status == "ended":
            return r
        time.sleep(0.02)
    return None


def test_build_app_enforces_auth_and_audits(fake_redis):
    """build_app 组装的 app:无 key->401,dev-key->200,且事件记入全局审计 ledger。"""
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "open.yaml"), "w", encoding="utf-8") as f:
        f.write("permissions: []\nmax_steps: 3\n")
    audit_dir = tempfile.mkdtemp()

    app = build_app(fake_redis, policy_dir=pol_dir, sanitization_dir=tempfile.mkdtemp(),
                    static_dir="", llm_mode="mock", auth_mode="api_key", audit_dir=audit_dir)
    client = TestClient(app)
    mgr = app.state.mgr
    audit_port = app.state.audit_port

    # 无 key -> 401
    r = client.post("/api/runs", json={"task": "x", "policy": "open.yaml", "sanitization": ""})
    assert r.status_code == 401

    # dev-key -> 200
    r = client.post("/api/runs", json={"task": "x", "policy": "open.yaml", "sanitization": ""},
                    headers={"Authorization": "Bearer dev-key"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    _wait_ended(mgr, run_id)

    # 全局审计 ledger 收到了事件(run.started / run.ended 至少各一)
    entries = __import__("asyncio").new_event_loop().run_until_complete(audit_port._ledger.read_all())
    assert len(entries) >= 2
    tools = {e.tool for e in entries}
    # 事件经 event_to_agent_json:run.* 的 tool 字段为空,但有 session_id
    assert all(e.session_id for e in entries)


def test_build_app_auth_none_is_dev_mode(fake_redis):
    """auth_mode='none' -> 不验证(开发模式),无 key 也能 200。"""
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "open.yaml"), "w", encoding="utf-8") as f:
        f.write("permissions: []\nmax_steps: 3\n")
    app = build_app(fake_redis, policy_dir=pol_dir, sanitization_dir=tempfile.mkdtemp(),
                    static_dir="", llm_mode="mock", auth_mode="none")
    client = TestClient(app)
    r = client.post("/api/runs", json={"task": "x", "policy": "open.yaml", "sanitization": ""})
    assert r.status_code == 200
