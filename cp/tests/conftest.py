import pytest_asyncio
import fakeredis.aioredis


@pytest_asyncio.fixture
async def fake_redis():
    """每个测试一个独立的内存 Redis(async)。测试结束清空。"""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.flushall()
    await r.aclose()
