from cp.adapters.local_state import RedisStatePort


async def test_save_and_get_session(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"identity": "alice", "used_steps": 5})
    got = await sp.get_session("s1")
    assert got == {"identity": "alice", "used_steps": 5}


async def test_get_missing_session_returns_none(fake_redis):
    sp = RedisStatePort(fake_redis)
    assert await sp.get_session("nope") is None


async def test_delete_session(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"x": 1})
    await sp.delete_session("s1")
    assert await sp.get_session("s1") is None


async def test_save_overwrites(fake_redis):
    sp = RedisStatePort(fake_redis)
    await sp.save_session("s1", {"v": 1})
    await sp.save_session("s1", {"v": 2})
    assert (await sp.get_session("s1"))["v"] == 2


async def test_two_instances_share_state(fake_redis):
    """约束6:控制面无状态。两个 StatePort 共享同一 Redis,状态一致。"""
    sp1 = RedisStatePort(fake_redis)
    sp2 = RedisStatePort(fake_redis)
    await sp1.save_session("s1", {"v": 1})
    assert (await sp2.get_session("s1")) == {"v": 1}
