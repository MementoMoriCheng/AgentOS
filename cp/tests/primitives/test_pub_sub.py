from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.primitives.registry import PrimitiveContext
from cp.primitives.pub import PubPrimitive
from cp.primitives.sub import SubPrimitive
from cp.resource import Resource


async def test_pub_publishes_to_stream(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    result = await PubPrimitive().execute(ctx, {"topic": "agent.s1.event", "payload": {"type": "done"}})
    assert result.status == "success"
    # 验证事件持久化在 Stream
    entries = await fake_redis.xrange("agent.s1.event")
    assert len(entries) == 1


async def test_pub_permission_key():
    pk = PubPrimitive().permission_key({"topic": "t.x"})
    assert pk == Resource(type="topic", id="t.x")


async def test_pub_no_bus_error():
    ctx = PrimitiveContext(bus=None)
    result = await PubPrimitive().execute(ctx, {"topic": "t", "payload": {}})
    assert result.status == "error"


async def test_sub_registers_subscription(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    result = await SubPrimitive().execute(ctx, {"topic": "agent.s1.event", "handler_desc": "log it"})
    assert result.status == "success"
    assert result.data["subscribed"] is True
    assert result.data["handler_desc"] == "log it"


async def test_sub_permission_key():
    pk = SubPrimitive().permission_key({"topic": "t.y"})
    assert pk == Resource(type="topic", id="t.y")


async def test_sub_no_bus_error():
    ctx = PrimitiveContext(bus=None)
    result = await SubPrimitive().execute(ctx, {"topic": "t", "handler_desc": "x"})
    assert result.status == "error"
