import tempfile
from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.policy.policy import Policy, Rule
from cp.resource import Resource
from cp.sanitize.sanitizer import Sanitizer, FieldRule
from cp.session.session import Session
from cp.tools.tool import Registry, ToolResult


class StubTool:
    def __init__(self, name, data=None, raise_err=False):
        self._name = name
        self._data = data or {}
        self._raise = raise_err

    def name(self):
        return self._name

    def schema(self):
        return '{"name":"%s"}' % self._name

    def permission_key(self, params):
        return Resource(type="path", id=params.get("path", ""))

    async def execute(self, ctx, params):
        if self._raise:
            raise RuntimeError("boom")
        return ToolResult(data=dict(self._data))


def _session(tmpdir, rules, san_rules=None):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    san = Sanitizer.new_from_rules(san_rules or [])
    ledger = Ledger(tmpdir + "/a.log")
    return Session.new("s1", "local", pol, san, ledger)


async def test_pipeline_allows_and_returns_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "hello"}))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = await pipe.call(sess, sid, "fs_read", {"path": "examples/x"})
        assert resp.allowed
        assert resp.result["content"] == "hello"


async def test_pipeline_denies_unknown_tool():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        sandbox = LocalSandboxExecutor(Registry())
        pipe = Pipeline(Registry(), bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = await pipe.call(sess, "sid", "shell_exec", {"path": "rm -rf /"})
        assert not resp.allowed


async def test_pipeline_denies_unauthorized_path():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = await pipe.call(sess, sid, "fs_read", {"path": "/etc/shadow"})
        assert not resp.allowed


async def test_pipeline_sanitizes_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"phone": "13812341234", "amount": 120}))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])],
                        [FieldRule("phone", "mask", 3, 4)])
        resp = await pipe.call(sess, sid, "fs_read", {"path": "examples/x"})
        assert resp.result["phone"] == "138****1234"
        assert resp.result["amount"] == 120


async def test_pipeline_publishes_tool_called_event():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "y"}))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        seen = []
        async def handler(e):
            seen.append(e)
        bus.subscribe(handler)
        await pipe.call(sess, sid, "fs_read", {"path": "examples/x"})
        assert any(e.type == "tool.called" for e in seen)


async def test_pipeline_quota_exceeded_terminates():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        pol = Policy(permissions=[Rule("path", "examples/**", ["fs_read"])],
                     max_steps=1, max_tokens=100000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        await pipe.call(sess, sid, "fs_read", {"path": "examples/x"})
        resp = await pipe.call(sess, sid, "fs_read", {"path": "examples/y"})
        assert resp.errored
        assert "quota" in resp.message


async def test_pipeline_execute_error_publishes_errored_event():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", raise_err=True))
        sandbox = LocalSandboxExecutor(reg)
        sid = await sandbox.create({})
        pipe = Pipeline(reg, bus, sandbox)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        seen = []
        async def handler(e):
            seen.append(e)
        bus.subscribe(handler)
        resp = await pipe.call(sess, sid, "fs_read", {"path": "examples/x"})
        assert resp.errored
        assert resp.message == "tool error"
        assert any(e.type == "tool.errored" for e in seen)
