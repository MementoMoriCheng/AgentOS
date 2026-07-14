import asyncio

from cp.scheduler.scheduler import Scheduler


async def test_acquire_release_allows_reuse():
    s = Scheduler(2)
    r1 = await s.acquire()
    r2 = await s.acquire()
    r1()
    r2()
    r3 = await s.acquire()  # 应立即拿到
    r3()


async def test_concurrency_limit_enforced():
    s = Scheduler(1)
    held = asyncio.Event()
    release_evt = asyncio.Event()

    async def holder():
        r = await s.acquire()
        held.set()
        await release_evt.wait()
        r()

    h_task = asyncio.create_task(holder())
    await held.wait()
    # 此时槽被占,acquire 应阻塞
    got = asyncio.Event()

    async def waiter():
        r = await s.acquire()
        got.set()
        r()

    w_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    assert not got.is_set()  # 仍阻塞
    release_evt.set()
    await h_task
    await w_task
    assert got.is_set()
