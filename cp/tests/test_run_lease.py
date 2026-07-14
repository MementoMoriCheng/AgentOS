from cp.server.run_lease import RedisRunLease


async def test_acquire_succeeds_first_time(fake_redis):
    lease = RedisRunLease(fake_redis)
    assert await lease.acquire("run-1") is True


async def test_acquire_fails_if_held(fake_redis):
    a = RedisRunLease(fake_redis)
    b = RedisRunLease(fake_redis)
    assert await a.acquire("run-1") is True
    assert await b.acquire("run-1") is False  # A 持有


async def test_release_allows_other(fake_redis):
    a = RedisRunLease(fake_redis)
    b = RedisRunLease(fake_redis)
    await a.acquire("run-1")
    await a.release("run-1")
    assert await b.acquire("run-1") is True


async def test_renew_extends_for_holder(fake_redis):
    a = RedisRunLease(fake_redis, ttl=1)
    await a.acquire("run-1")
    assert await a.renew("run-1") is True


async def test_renew_fails_for_non_holder(fake_redis):
    a = RedisRunLease(fake_redis)
    b = RedisRunLease(fake_redis)
    await a.acquire("run-1")
    assert await b.renew("run-1") is False  # B 不是持有者


async def test_holder_returns_replica_id(fake_redis):
    a = RedisRunLease(fake_redis)
    await a.acquire("run-1")
    h = await a.holder("run-1")
    assert h is not None
    assert h.startswith("replica-")
    assert h == a.replica_id


async def test_holder_none_when_unheld(fake_redis):
    lease = RedisRunLease(fake_redis)
    assert await lease.holder("run-1") is None
