import asyncio
from cp.adapters.redis_bus import RedisStreamMessageBus


async def test_publish_and_subscribe(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    received = []
    async def handler(msg):
        received.append(msg)
    bus.subscribe("actions.s1", handler)
    await bus.start()
    await bus.publish("actions.s1", {"cmd": "ls"})
    await asyncio.sleep(0.15)  # let consume loop process
    await bus.stop()
    assert len(received) == 1
    assert received[0]["cmd"] == "ls"


async def test_replay_from_history(fake_redis):
    """约束4:事件持久化在 Stream,可 replay。新订阅者从头消费。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.publish("obs.s1", {"step": 1})
    await bus.publish("obs.s1", {"step": 2})
    received = []
    async def handler(msg):
        received.append(msg)
    bus.subscribe("obs.s1", handler)
    await bus.start()
    await asyncio.sleep(0.2)
    await bus.stop()
    assert len(received) == 2
    assert received[0]["step"] == 1
    assert received[1]["step"] == 2


async def test_multiple_subscribers(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    a = []
    b = []
    async def ha(msg):
        a.append(msg)
    async def hb(msg):
        b.append(msg)
    bus.subscribe("ev.s1", ha)
    bus.subscribe("ev.s1", hb)
    await bus.start()
    await bus.publish("ev.s1", {"x": 1})
    await asyncio.sleep(0.15)
    await bus.stop()
    assert len(a) == 1 and len(b) == 1


async def test_publish_persists_to_stream(fake_redis):
    """XADD persists to Stream even without subscribers."""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.publish("t.s1", {"v": 1})
    entries = await fake_redis.xrange("t.s1")
    assert len(entries) == 1


async def test_unsubscribe_stops_delivery(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    received = []
    async def handler(msg):
        received.append(msg)
    unsub = bus.subscribe("u.s1", handler)
    await bus.start()
    await bus.publish("u.s1", {"v": 1})
    await asyncio.sleep(0.15)
    unsub()
    await bus.publish("u.s1", {"v": 2})
    await asyncio.sleep(0.15)
    await bus.stop()
    assert len(received) == 1
