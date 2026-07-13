from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.policy.policy import Policy, Rule
from cp.sanitize.sanitizer import Sanitizer, FieldRule
from cp.session.account import ResourceQuota
from cp.session.session import Session
from cp.audit.ledger import Ledger
from cp.tools.tool import Registry, ToolResult
from cp.resource import Resource

import json
import tempfile


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

    def execute(self, ctx, params):
        if self._raise:
            raise RuntimeError("boom")
        return ToolResult(data=dict(self._data))


def _session(tmpdir, rules, san_rules=None):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    san = Sanitizer.new_from_rules(san_rules or [])
    ledger = Ledger(tmpdir + "/a.log")
    return Session.new("s1", "local", pol, san, ledger)


def test_pipeline_allows_and_returns_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "hello"}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "fs_read", {"path": "examples/x"})
        assert resp.allowed
        assert resp.result["content"] == "hello"


def test_pipeline_denies_unknown_tool():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        pipe = Pipeline(Registry(), bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "shell_exec", {"path": "rm -rf /"})
        assert not resp.allowed


def test_pipeline_denies_unauthorized_path():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        resp = pipe.call(sess, "fs_read", {"path": "/etc/shadow"})
        assert not resp.allowed


def test_pipeline_sanitizes_result():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"phone": "13812341234", "amount": 120}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])],
                        [FieldRule("phone", "mask", 3, 4)])
        resp = pipe.call(sess, "fs_read", {"path": "examples/x"})
        assert resp.result["phone"] == "138****1234"  # 4 stars: 11-3-4=4
        assert resp.result["amount"] == 120


def test_pipeline_publishes_tool_called_event():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read", {"content": "y"}))
        pipe = Pipeline(reg, bus)
        sess = _session(d, [Rule("path", "examples/**", ["fs_read"])])
        seen = []
        bus.subscribe(lambda e: seen.append(e))
        pipe.call(sess, "fs_read", {"path": "examples/x"})
        types = [e.type for e in seen]
        assert "tool.called" in types


def test_pipeline_quota_exceeded_terminates():
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = Registry()
        reg.register(StubTool("fs_read"))
        pipe = Pipeline(reg, bus)
        pol = Policy(permissions=[Rule("path", "examples/**", ["fs_read"])],
                     max_steps=1, max_tokens=100000)
        sess = Session.new("s1", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        pipe.call(sess, "fs_read", {"path": "examples/x"})  # 用掉唯一一步
        resp = pipe.call(sess, "fs_read", {"path": "examples/y"})
        assert resp.errored
        assert "quota" in resp.message
