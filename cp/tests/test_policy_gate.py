from cp.policy.policy import Policy, Rule, load_from_file
from cp.policy.gate import Gate
from cp.resource import Resource


def _gate_with(rules):
    return Gate(Policy(permissions=rules, max_steps=20))


def test_gate_allows_read_under_workspace():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read", "fs_list"])])
    assert g.allowed("fs_read", Resource("path", "examples/workspace/sales.csv"))
    assert g.allowed("fs_read", Resource("path", "examples/workspace"))


def test_gate_denies_write_outside_out_dir():
    g = _gate_with([
        Rule("path", "examples/workspace/**", ["fs_read", "fs_list"]),
        Rule("path", "examples/workspace/out/**", ["fs_write"]),
    ])
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/sales.csv"))
    assert not g.allowed("fs_write", Resource("path", "examples/workspace/evil.txt"))
    assert g.allowed("fs_write", Resource("path", "examples/workspace/out/total.txt"))


def test_gate_denies_absolute_path():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("fs_read", Resource("path", "/etc/shadow"))
    assert not g.allowed("fs_read", Resource("path", "C:/Windows/System32/config/SAM"))


def test_gate_denies_traversal():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    for attack in [
        "examples/workspace/../../../../etc/passwd",
        "examples/workspace/../../../.ssh/id_rsa",
        "examples/workspace/out/../../../secret",
    ]:
        assert not g.allowed("fs_read", Resource("path", attack)), attack


def test_gate_denies_unknown_action():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("shell_exec", Resource("path", "rm -rf /"))


def test_gate_denies_unknown_resource_type():
    g = _gate_with([Rule("path", "examples/workspace/**", ["fs_read"])])
    assert not g.allowed("db_query", Resource("db_table", "orders"))


def test_gate_exact_match_for_non_path_type():
    g = _gate_with([Rule("db_table", "sales.orders", ["db_query"])])
    assert g.allowed("db_query", Resource("db_table", "sales.orders"))
    assert not g.allowed("db_query", Resource("db_table", "finance.salaries"))


def test_load_from_file_reads_real_policy():
    p = load_from_file("examples/policies/data_analyst.yaml")
    assert p.agent_role == "data_analyst"
    assert p.max_steps == 20
    assert len(p.permissions) == 2
