"""架构验证:开闭原则。加新工具只需实现 Tool 接口 + 注册,核心(Pipeline/Gate)零改。
移植自 kernel/test/architecture/open_closed_test.go。"""
import json
import tempfile

from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.policy.policy import Policy, Rule
from cp.resource import Resource
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session
from cp.tools.tool import Registry, ToolResult


class DBQueryStub:
    """一个全新的、和 fs 完全无关的工具。证明加新工具核心零改。"""

    def name(self) -> str:
        return "db_query"

    def schema(self) -> str:
        return '{"name":"db_query","description":"stub"}'

    def permission_key(self, params):
        return Resource(type="db_table", id=params.get("table", ""))

    def execute(self, ctx, params):
        return ToolResult(data={"rows": [{"id": 1}]})


def _session(rules):
    pol = Policy(permissions=rules, max_steps=10, max_tokens=100000)
    with tempfile.TemporaryDirectory() as d:
        return Session.new("arch-test", "local", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))


def test_open_closed_adding_new_tool_requires_zero_kernel_changes():
    sess = _session([Rule("db_table", "sales.orders", ["db_query"])])
    reg = Registry()
    reg.register(DBQueryStub())  # 注册新工具——唯一新增的代码
    bus = InProcess()
    pipe = Pipeline(reg, bus)

    # 允许查询 sales.orders(Gate 用 db_table 规则匹配,无需认识 db_query 工具)
    resp = pipe.call(sess, "db_query", {"table": "sales.orders"})
    assert resp.allowed
    assert len(resp.result["rows"]) == 1

    # 拒绝查询未授权的表(finance.salaries 不匹配 sales.orders 模式)
    resp = pipe.call(sess, "db_query", {"table": "finance.salaries"})
    assert not resp.allowed


def test_open_closed_new_tool_publishes_events():
    sess = _session([Rule("db_table", "sales.orders", ["db_query"])])
    reg = Registry()
    reg.register(DBQueryStub())
    bus = InProcess()
    pipe = Pipeline(reg, bus)

    saw = []
    bus.subscribe(lambda e: saw.append(e))
    pipe.call(sess, "db_query", {"table": "sales.orders"})
    assert any(e.type == "tool.called" and e.tool == "db_query" for e in saw)
