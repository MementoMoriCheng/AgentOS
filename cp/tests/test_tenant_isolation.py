import os
import tempfile

from cp.auth.auth import Identity
from cp.policy.gate import Gate
from cp.policy.policy import load_from_file
from cp.resource import Resource
from cp.server.runmgr import _tenant_policy_path


def _acme_policy(d):
    p = os.path.join(d, "acme.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write("permissions:\n"
                "  - resource_type: path\n"
                "    pattern: 'data/acme/**'\n"
                "    actions: [read]\n"
                "max_steps: 5\n")
    return p


def test_tenant_gate_allows_own_paths():
    """租户 'acme' policy 允许 data/acme/** 的 read。"""
    with tempfile.TemporaryDirectory() as d:
        gate = Gate(load_from_file(_acme_policy(d)))
        assert gate.allowed("read", Resource("path", "data/acme/sales.csv"))
        assert gate.allowed("read", Resource("path", "data/acme/sub/x.json"))


def test_tenant_gate_denies_cross_tenant_paths():
    """acme 的 gate 拒绝读别的租户的路径,也拒绝 write。"""
    with tempfile.TemporaryDirectory() as d:
        gate = Gate(load_from_file(_acme_policy(d)))
        assert not gate.allowed("read", Resource("path", "data/other/secret.txt"))
        assert not gate.allowed("write", Resource("path", "data/acme/x"))


def test_tenant_policy_resolved_when_identity_set():
    """identity.tenant='acme' 且存在 acme.yaml -> 解析到 acme.yaml。"""
    with tempfile.TemporaryDirectory() as d:
        acme = _acme_policy(d)
        base = os.path.join(d, "open.yaml")
        with open(base, "w", encoding="utf-8") as f:
            f.write("permissions: []\nmax_steps: 5\n")
        resolved = _tenant_policy_path(base, Identity(tenant="acme", user="alice"))
        assert resolved == acme


def test_default_tenant_uses_requested_policy():
    """default/None tenant -> 用原 policy_path(不切换)。"""
    base = os.path.join(os.sep, "some", "dir", "open.yaml")
    assert _tenant_policy_path(base, Identity(tenant="default", user="x")) == base
    assert _tenant_policy_path(base, None) == base


def test_missing_tenant_policy_falls_back():
    """identity.tenant 指定但对应 yaml 不存在 -> 回退原 policy_path。"""
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "open.yaml")
        with open(base, "w", encoding="utf-8") as f:
            f.write("permissions: []\nmax_steps: 5\n")
        resolved = _tenant_policy_path(base, Identity(tenant="ghost", user="x"))
        assert resolved == base
