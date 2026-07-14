from cp.primitives.registry import PrimitiveContext
from cp.primitives.llm import LlmPrimitive
from cp.primitives.io import IoPrimitive
from cp.resource import Resource


def _ctx():
    return PrimitiveContext()


async def test_llm_returns_mock_response():
    prim = LlmPrimitive()
    result = await prim.execute(_ctx(), {"model": "deepseek", "messages": [{"role": "user", "content": "hello world"}]})
    assert result.status == "success"
    assert "[mock llm]" in result.data["content"]
    assert result.data["model"] == "deepseek"
    assert result.data["tokens_in"] > 0


async def test_llm_permission_key():
    pk = LlmPrimitive().permission_key({"model": "claude"})
    assert pk == Resource(type="llm", id="claude")


async def test_io_returns_mock_response():
    prim = IoPrimitive()
    result = await prim.execute(_ctx(), {"protocol": "http", "endpoint": "https://api.example.com/x"})
    assert result.status == "success"
    assert result.data["status"] == 200
    assert "api.example.com" in result.data["body"]


async def test_io_permission_key():
    pk = IoPrimitive().permission_key({"protocol": "http", "endpoint": "https://x.com"})
    assert pk.type == "http_url"
    assert pk.id == "https://x.com"


async def test_llm_handles_empty_messages():
    result = await LlmPrimitive().execute(_ctx(), {"model": "m", "messages": []})
    assert result.status == "success"
