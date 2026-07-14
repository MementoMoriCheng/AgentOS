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
    """build_app 组装的 app:无 key->401,dev-key->200(认证闸门)。
    只断言 HTTP 闸门,不等后台 run 完成——审计 hash 链闭环由
    test_api_e2e.test_week8_audit_hash_chain_intact_after_authenticated_run(async,稳健)覆盖。"""
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "open.yaml"), "w", encoding="utf-8") as f:
        f.write("permissions: []\nmax_steps: 3\n")

    app = build_app(fake_redis, policy_dir=pol_dir, sanitization_dir=tempfile.mkdtemp(),
                    static_dir="", llm_mode="mock", auth_mode="api_key",
                    audit_dir=tempfile.mkdtemp())
    client = TestClient(app)

    # 无 key -> 401
    r = client.post("/api/runs", json={"task": "x", "policy": "open.yaml", "sanitization": ""})
    assert r.status_code == 401

    # dev-key -> 200,run 创建
    r = client.post("/api/runs", json={"task": "x", "policy": "open.yaml", "sanitization": ""},
                    headers={"Authorization": "Bearer dev-key"})
    assert r.status_code == 200
    assert "run_id" in r.json()


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
