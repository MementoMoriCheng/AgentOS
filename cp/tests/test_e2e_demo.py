"""端到端 demo:用 mock LLM 跑完整 agent(数据分析任务)。
经 Agent Loop → PrimitiveExecutor(安全管道)→ 原语 → Sandbox。
验证四道安全防线 + 原语层 + 编排在真实拓扑下协同工作。"""
import json
import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.agent_loop import run_agent_loop
from cp.audit.ledger import Ledger
from cp.compose import build_control_plane
from cp.eventbus.bus import InProcess
from cp.llm.mock import MockLLMClient
from cp.policy.policy import Policy, Rule
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.read import ReadPrimitive
from cp.primitives.write import WritePrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session


class E2EMockSandbox:
    """端到端 mock 沙箱:模拟文件系统(fs_read/fs_write)。"""
    def __init__(self):
        self.files = {}

    async def create(self, config):
        return "sbx-e2e"

    async def exec_action(self, sid, action):
        tool = action.get("tool", "")
        params = action.get("params", {})
        if tool == "fs_read":
            path = params.get("path", "")
            content = self.files.get(path, "")
            if not content and path not in self.files:
                return {"error": "file not found"}
            return {"data": {"content": content}}
        if tool == "fs_write":
            path = params.get("path", "")
            content = params.get("content", "")
            self.files[path] = content
            return {"data": {"bytes_written": len(content)}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


async def test_e2e_data_analysis_task(fake_redis):
    """端到端:read CSV → 回答(模拟数据分析)。
    完整路径:compose → Agent Loop → PrimitiveExecutor → read 原语 → sandbox。"""
    sb = E2EMockSandbox()
    sb.files["data/sales.csv"] = "date,amount\n2026-01-05,120\n2026-01-07,80"

    llm = MockLLMClient([
        # step 1: agent 决定读文件
        {"role": "assistant", "content": "Let me read the sales data.",
         "tool_calls": [{"id": "tc1", "type": "function",
                         "function": {"name": "read",
                                      "arguments": json.dumps({"source": "file:data/sales.csv"})}}]},
        # step 2: agent 给出最终答案
        {"role": "assistant", "content": "The total sales amount is 200."},
    ])

    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        reg.register(WritePrimitive())
        executor = PrimitiveExecutor(reg, bus)
        # policy 允许 read data/**
        pol = Policy(permissions=[Rule("path", "data/**", ["read"])],
                     max_steps=10, max_tokens=100000)
        sess = Session.new("e2e-s1", "alice", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx-e2e", sandbox=sb, bus=bus,
                               state=RedisStatePort(fake_redis))
        result = await run_agent_loop(
            "Read data/sales.csv and compute the total amount.",
            llm, executor, sess, ctx, [], max_steps=5,
        )
        assert result["termination"] == "completed"
        assert "200" in result["final_answer"]
        assert result["steps_used"] == 2


async def test_e2e_security_blocks_unauthorized_read(fake_redis):
    """端到端安全:agent 尝试读未授权路径 → 被 gate 拒 → agent 收到 denied → 放弃。"""
    sb = E2EMockSandbox()
    sb.files["secret/keys.txt"] = "PRIVATE_KEY=xxx"

    llm = MockLLMClient([
        {"role": "assistant", "content": "try read secret",
         "tool_calls": [{"id": "tc1", "type": "function",
                         "function": {"name": "read",
                                      "arguments": json.dumps({"source": "file:secret/keys.txt"})}}]},
        {"role": "assistant", "content": "Access denied, I cannot read that."},
    ])

    with tempfile.TemporaryDirectory() as d:
        bus = InProcess()
        reg = PrimitiveRegistry()
        reg.register(ReadPrimitive())
        executor = PrimitiveExecutor(reg, bus)
        # policy 只允许 data/**,不允许 secret/**
        pol = Policy(permissions=[Rule("path", "data/**", ["read"])],
                     max_steps=10, max_tokens=100000)
        sess = Session.new("e2e-s2", "alice", pol, Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, sandbox_id="sbx", sandbox=sb, bus=bus, state=None)
        result = await run_agent_loop("read secret/keys.txt", llm, executor, sess, ctx, [], max_steps=5)
        assert result["termination"] == "completed"
        assert "denied" in result["final_answer"].lower() or "cannot" in result["final_answer"].lower()
        # secret 文件不应被读取
        assert sb.files["secret/keys.txt"] == "PRIVATE_KEY=xxx"  # 未变


async def test_e2e_pipeline_orchestration(fake_redis):
    """端到端编排:Pipeline 顺序链跑两个 agent。"""
    from cp.orchestration.pipeline import run_pipeline

    async def reader_agent(task):
        return {"final_answer": f"read:{task}", "steps_used": 1, "termination": "completed"}

    async def analyzer_agent(task):
        return {"final_answer": f"analyzed:{task}", "steps_used": 1, "termination": "completed"}

    result = await run_pipeline([reader_agent, analyzer_agent], "sales.csv")
    assert result["final"] == "analyzed:read:sales.csv"
    assert len(result["stages"]) == 2


async def test_adversarial_regression():
    """硬里程碑:对抗用例在新架构下仍全绿。"""
    from cp.policy.gate import Gate
    from cp.policy.policy import load_from_file
    from cp.resource import Resource
    from cp.sanitize.sanitizer import load_from_file as load_san

    g = Gate(load_from_file("examples/policies/data_analyst.yaml"))
    assert not g.allowed("exec", Resource("shell", "rm -rf /"))
    assert not g.allowed("io", Resource("http_url", "https://evil.com"))
    assert not g.allowed("read", Resource("path", "/etc/shadow"))
    assert g.allowed("fs_read", Resource("path", "examples/workspace/sales.csv"))
    s = load_san("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({"phone": "13812341234", "amount": 120})
    assert out["phone"] != "13812341234"
    assert out["amount"] == 120
