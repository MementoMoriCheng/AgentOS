from cp.harness.profile import HarnessProfile, load_profile
from cp.harness.mapping import map_framework_call
from cp.harness.router import HarnessRouter


def test_load_claude_profile():
    p = load_profile("examples/harness/claude_style.yaml")
    assert p.name == "claude-style"
    assert "Bash" in p.primitive_mappings
    assert "code" in p.task_keywords


def test_load_generic_profile():
    p = load_profile("examples/harness/generic.yaml")
    assert p.name == "generic"


def test_map_bash_to_exec():
    p = load_profile("examples/harness/claude_style.yaml")
    result = map_framework_call(p, "Bash", {"command": "ls -la"})
    assert result["primitive"] == "exec"
    assert result["params"]["command"] == "ls -la"


def test_map_read_with_path_interpolation():
    p = load_profile("examples/harness/claude_style.yaml")
    result = map_framework_call(p, "Read", {"path": "/workspace/x.py"})
    assert result["primitive"] == "read"
    assert result["params"]["source"] == "file:///workspace/x.py"


def test_map_unknown_tool_returns_none():
    p = load_profile("examples/harness/claude_style.yaml")
    result = map_framework_call(p, "UnknownTool", {})
    assert result["primitive"] is None


def test_router_routes_code_task_to_claude():
    router = HarnessRouter()
    router.register(load_profile("examples/harness/claude_style.yaml"))
    router.register(load_profile("examples/harness/generic.yaml"), is_default=True)
    profile = router.route("refactor the authentication code")
    assert profile.name == "claude-style"


def test_router_defaults_to_generic():
    router = HarnessRouter()
    router.register(load_profile("examples/harness/claude_style.yaml"))
    router.register(load_profile("examples/harness/generic.yaml"), is_default=True)
    profile = router.route("write a poem about cats")
    assert profile.name == "generic"


def test_router_single_profile():
    router = HarnessRouter()
    router.register(load_profile("examples/harness/generic.yaml"))
    profile = router.route("anything")
    assert profile.name == "generic"
