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
