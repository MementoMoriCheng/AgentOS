"""Week 6 T6: RedisRunStore — run 元数据 + 事件的外部存储。"""
import json

from cp.server.redis_store import RedisRunStore


async def test_meta_roundtrip(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.save_meta("r1", {"run_id": "r1", "status": "running", "started_at": 1.5})
    m = await s.get_meta("r1")
    assert m["run_id"] == "r1"
    assert m["status"] == "running"
    assert m["started_at"] == 1.5
    assert await s.get_meta("missing") is None


async def test_meta_update(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.save_meta("r1", {"run_id": "r1", "status": "running"})
    await s.save_meta("r1", {"run_id": "r1", "status": "ended", "final_answer": "done"})
    m = await s.get_meta("r1")
    assert m["status"] == "ended"
    assert m["final_answer"] == "done"


async def test_events_append_and_list(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.append_event("r1", {"type": "run.started"})
    await s.append_event("r1", {"type": "primitive.called", "tool": "read"})
    evs = await s.get_events("r1")
    assert [e["type"] for e in evs] == ["run.started", "primitive.called"]
    assert evs[1]["tool"] == "read"


async def test_list_runs_scans_meta(fake_redis):
    s = RedisRunStore(fake_redis)
    await s.save_meta("r1", {"run_id": "r1", "task": "a"})
    await s.save_meta("r2", {"run_id": "r2", "task": "b"})
    runs = await s.list_runs()
    ids = {r["run_id"] for r in runs}
    assert ids == {"r1", "r2"}


async def test_list_runs_empty(fake_redis):
    s = RedisRunStore(fake_redis)
    assert await s.list_runs() == []


async def test_publish_to_channel(fake_redis):
    """append_event publish 到 channel;订阅者收到实时事件。"""
    s = RedisRunStore(fake_redis)
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(s.channel("r1"))
    await s.append_event("r1", {"type": "run.ended"})
    # pubsub 先收到 subscribe 确认(type=subscribe),再是真实消息(type=message)
    msg = None
    for _ in range(5):
        m = await pubsub.get_message(timeout=1.0)
        if m and m.get("type") == "message":
            msg = m
            break
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "run.ended"
