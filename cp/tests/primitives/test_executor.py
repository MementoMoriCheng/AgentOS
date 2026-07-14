import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.policy.policy import Policy, Rule
from cp.primitives.exec import ExecPrimitive
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.sanitize.sanitizer import FieldRule, Sanitizer
from cp.session.session import Session


class MockSandbox:
    async def create(self, config):
        return "sbx-mock"

    async def exec_action(self, sid, action):
        tool = action.get("tool", "")
        if tool == "fs_read":
            return {"data": {"content": "data with phone 13812341234"}}
        return {"data": {"mock": True}}

    async def destroy(self, sid):
        pass


def _session(tmpdir, rules, san_rules=None):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    san = Sanitizer.new_from_rules(san_rules or [])
    return Session.new("s1", "local", pol, san, Ledger(tmpdir + "/a.log"))


def _registry():
    reg = PrimitiveRegistry()
    reg.register(ReadPrimitive())
    reg.register(ExecPrimitive())
    return reg


async def test_executor_allows_permitted_primitive():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = _registry()
        ex = PrimitiveExecutor(reg, bus)
        # 用相对路径 file:examples/... —— gate 拒绝绝对路径
        sess = _session(d, [Rule("path", "examples/workspace/**", ["read"])])
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        resp = await ex.call(sess, ctx, "read", {"source": "file:examples/workspace/x.txt"})
        assert resp.allowed


async def test_executor_denies_unpermitted_primitive():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = _registry()
        ex = PrimitiveExecutor(reg, bus)
        # policy 只允许 read path,不允许 exec shell
        sess = _session(d, [Rule("path", "examples/workspace/**", ["read"])])
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        resp = await ex.call(sess, ctx, "exec", {"command": "rm -rf /"})
        assert not resp.allowed


async def test_executor_denies_unknown_primitive():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        ex = PrimitiveExecutor(_registry(), bus)
        sess = _session(d, [Rule("path", "examples/**", ["read"])])
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        resp = await ex.call(sess, ctx, "nope", {})
        assert not resp.allowed
        assert "unknown" in resp.message


async def test_executor_sanitizes_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = _registry()
        ex = PrimitiveExecutor(reg, bus)
        sess = _session(d, [Rule("path", "examples/workspace/**", ["read"])],
                        [FieldRule("content", "mask")])
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        resp = await ex.call(sess, ctx, "read", {"source": "file:examples/workspace/x.txt"})
        assert resp.allowed
        # content 含 phone,应被 mask(MockSandbox 返回 "data with phone 13812341234")
        assert resp.result["content"] != "data with phone 13812341234"


async def test_executor_publishes_audit_event():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = _registry()
        ex = PrimitiveExecutor(reg, bus)
        sess = _session(d, [Rule("path", "examples/workspace/**", ["read"])])
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        seen = []

        async def handler(e):
            seen.append(e)

        bus.subscribe(handler)
        await ex.call(sess, ctx, "read", {"source": "file:examples/workspace/x.txt"})
        assert any(e.type == "primitive.called" for e in seen)


async def test_executor_quota_exceeded():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = _registry()
        ex = PrimitiveExecutor(reg, bus)
        pol = Policy(permissions=[Rule("path", "examples/**", ["read"])],
                     max_steps=1, max_tokens=100000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]),
                           Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=MockSandbox(),
                               bus=bus, state=None)
        await ex.call(sess, ctx, "read", {"source": "file:examples/x"})  # 用掉唯一一步
        resp = await ex.call(sess, ctx, "read", {"source": "file:examples/y"})
        assert resp.errored
        assert "quota" in resp.message
