"""Week 7 T2: sub 原语收消息写 inbox 验证。"""
import asyncio

from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.primitives.pub import PubPrimitive
from cp.primitives.registry import PrimitiveContext
from cp.primitives.sub import SubPrimitive


async def test_sub_writes_to_inbox(fake_redis):
    """sub 注册的 handler 收到 pub 的消息后写入 ctx.inbox。"""
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    # 先订阅
    r = await SubPrimitive().execute(ctx, {"topic": "updates", "handler_desc": "log updates"})
    assert r.status == "success"
    assert r.data["subscribed"] is True
    # 启动 bus 消费
    await bus.start()
    try:
        await PubPrimitive().execute(PrimitiveContext(bus=bus), {"topic": "updates", "payload": {"x": 1}})
        await asyncio.sleep(0.15)  # 等消费循环分发
    finally:
        await bus.stop()
    assert len(ctx.inbox["updates"]) == 1
    assert ctx.inbox["updates"][0] == {"x": 1}


async def test_sub_no_bus_returns_error():
    ctx = PrimitiveContext(bus=None)
    r = await SubPrimitive().execute(ctx, {"topic": "x"})
    assert r.status == "error"


async def test_sub_inbox_is_empty_until_message(fake_redis):
    """订阅后但无消息时 inbox 为空 list。"""
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    await SubPrimitive().execute(ctx, {"topic": "noop"})
    assert ctx.inbox["noop"] == []
