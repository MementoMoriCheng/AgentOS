"""对抗安全测试——护城河证明。忠实移植自 kernel/test/adversarial/adversarial_test.go。
8 个用例全部通过 = 安全逻辑从 Go 迁到 Python 零退化。"""
import os

from cp.policy.gate import Gate
from cp.policy.policy import load_from_file
from cp.resource import Resource
from cp.sanitize.sanitizer import load_from_file as load_san


def _load_real_gate() -> Gate:
    """加载 examples/policies/data_analyst.yaml,测随产品发布的真实策略。"""
    return Gate(load_from_file("examples/policies/data_analyst.yaml"))


async def test_adversarial_read_etc_shadow():
    assert not _load_real_gate().allowed("fs_read", Resource("path", "/etc/shadow"))


async def test_adversarial_read_abs_windows_secret():
    assert not _load_real_gate().allowed("fs_read",
                                         Resource("path", "C:/Windows/System32/config/SAM"))


async def test_adversarial_traversal_escape():
    g = _load_real_gate()
    attacks = [
        "examples/workspace/../../../../etc/passwd",
        "examples/workspace/../../../.ssh/id_rsa",
        "examples/workspace/out/../../../secret",
    ]
    for a in attacks:
        assert not g.allowed("fs_read", Resource("path", a)), a


async def test_adversarial_write_outside_out_dir():
    g = _load_real_gate()
    # data_analyst 只能写 examples/workspace/out/**
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/sales.csv"))
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/evil.txt"))


async def test_adversarial_unknown_tool():
    assert not _load_real_gate().allowed("shell_exec", Resource("path", "rm -rf /"))


async def test_adversarial_unknown_resource_type():
    assert not _load_real_gate().allowed("db_query", Resource("db_table", "orders"))


async def test_adversarial_network_disabled():
    assert not _load_real_gate().allowed("net_fetch", Resource("http_url", "https://evil.com/exfil"))


async def test_adversarial_sanitization_masks_pii():
    s = load_san("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({
        "phone": "13812341234",
        "customer_id": "C001",
        "remark": "secret",
        "amount": 120,
    })
    assert out["phone"] != "13812341234"
    assert out["customer_id"] != "C001"
    assert "remark" not in out
    assert out["amount"] == 120
