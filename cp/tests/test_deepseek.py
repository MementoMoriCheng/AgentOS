import os
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("RUN_INTEGRATION")),
    reason="integration test: set DEEPSEEK_API_KEY + RUN_INTEGRATION=1 to run",
)


async def test_deepseek_real_call():
    from cp.llm.deepseek import AsyncDeepSeekClient
    client = AsyncDeepSeekClient()
    result = await client.chat([
        {"role": "user", "content": "Reply with exactly: hello"}
    ])
    assert "content" in result
    assert len(result["content"]) > 0


async def test_llm_primitive_with_real_client():
    from cp.llm.deepseek import AsyncDeepSeekClient
    from cp.primitives.llm import LlmPrimitive
    from cp.primitives.registry import PrimitiveContext
    client = AsyncDeepSeekClient()
    prim = LlmPrimitive(client=client)
    ctx = PrimitiveContext()
    result = await prim.execute(ctx, {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "Reply with exactly: hello"}],
    })
    assert result.status == "success"
    assert result.data["content"]


async def test_real_llm_agent_loop():
    """真实 DeepSeek 跑完整 Agent Loop(无工具,单轮问答)。
    这是 HTTP 服务层 run_agent_loop 入口的真实端到端验证。"""
    import tempfile
    from cp.agent_loop import run_agent_loop
    from cp.audit.ledger import Ledger
    from cp.policy.policy import Policy
    from cp.sanitize.sanitizer import Sanitizer
    from cp.session.session import Session
    from cp.llm.deepseek import AsyncDeepSeekClient
    llm = AsyncDeepSeekClient()
    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local",
                           Policy(permissions=[], max_steps=3, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(os.path.join(d, "a.log")))
        result = await run_agent_loop("Reply with exactly: hello world", llm, None, sess, None, [])
        assert result["termination"] == "completed"
        assert "hello" in result["final_answer"].lower()
