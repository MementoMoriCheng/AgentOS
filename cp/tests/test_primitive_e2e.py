import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.audit.ledger import Ledger
from cp.eventbus.bus import InProcess
from cp.policy.policy import Policy, Rule
from cp.primitives.exec import ExecPrimitive
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.io import IoPrimitive
from cp.primitives.llm import LlmPrimitive
from cp.primitives.pub import PubPrimitive
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.primitives.sub import SubPrimitive
from cp.primitives.write import WritePrimitive
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session


class MockSandbox:
    async def create(self, config):
        return "sbx-e2e"

    async def exec_action(self, sid, action):
        tool = action.get("tool", "")
        if tool == "fs_read":
            return {"data": {"content": "hello from file"}}
        if tool == "fs_write":
            return {"data": {"bytes_written": 11}}
        if tool == "shell":
            return {"data": {"stdout": "done\n", "exit_code": 0}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


def _all_primitives():
    reg = PrimitiveRegistry()
    for p in [ExecPrimitive(), ReadPrimitive(), WritePrimitive(), LlmPrimitive(),
              IoPrimitive(), PubPrimitive(), SubPrimitive()]:
        reg.register(p)
    return reg


async def test_e2e_primitive_sequence(fake_redis):
    """端到端:read file → llm(处理)→ write kv,经安全管道 + 原语。"""
    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        state = RedisStatePort(fake_redis)
        reg = _all_primitives()
        executor = PrimitiveExecutor(reg, bus)
        # policy 允许 read path + write kv + llm
        # 非 path 资源是精确匹配:id == pattern。kv://results/out -> id "results/out";
        # llm permission_key 用 model 名 "mock"。
        pol = Policy(permissions=[
            Rule("path", "examples/data/**", ["read"]),
            Rule("kv", "results/out", ["write"]),
            Rule("llm", "mock", ["llm"]),
        ], max_steps=10, max_tokens=100000)
        sess = Session.new("s2", "alice", pol, Sanitizer.new_from_rules([]),
                           Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx-e2e", sandbox=MockSandbox(),
                               bus=RedisStreamMessageBus(fake_redis), state=state)
        # step 1: read a file (相对路径,经 MockSandbox fs_read)
        r1 = await executor.call(sess, ctx, "read", {"source": "file:examples/data/input.txt"})
        assert r1.allowed
        content = r1.result["content"]
        # step 2: llm process (mock)
        r2 = await executor.call(sess, ctx, "llm",
                                 {"model": "mock", "messages": [{"role": "user", "content": content}]})
        assert r2.allowed
        # step 3: write result to kv
        r3 = await executor.call(sess, ctx, "write",
                                 {"target": "kv://results/out", "data": r2.result["content"]})
        assert r3.allowed
        # verify written (kv://results/out -> key "results/out")
        stored = await state.get_session("results/out")
        assert stored is not None


async def test_e2e_all_seven_primitives_registered():
    reg = _all_primitives()
    names = set(reg.names())
    assert names == {"exec", "read", "write", "llm", "io", "pub", "sub"}


async def test_adversarial_regression_still_green():
    """硬里程碑:对抗用例在原语路径下仍全绿。重新验证 Gate + Sanitizer。"""
    from cp.policy.gate import Gate
    from cp.policy.policy import load_from_file
    from cp.resource import Resource
    from cp.sanitize.sanitizer import load_from_file as load_san

    g = Gate(load_from_file("examples/policies/data_analyst.yaml"))
    assert not g.allowed("exec", Resource("shell", "rm -rf /"))
    assert not g.allowed("io", Resource("http_url", "https://evil.com"))
    assert g.allowed("fs_read", Resource("path", "examples/workspace/sales.csv"))
    s = load_san("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({"phone": "13812341234", "amount": 120})
    assert out["phone"] != "13812341234"
    assert out["amount"] == 120
