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


async def test_runmgr_marks_leased_elsewhere_when_acquire_fails(fake_redis):
    """_run_agent 拿不到租约(acquire False)时,run 标 leased_elsewhere 且不执行。"""
    import asyncio
    import os
    import tempfile
    import time
    from cp.adapters.local_sandbox import LocalSandboxExecutor
    from cp.adapters.local_state import RedisStatePort
    from cp.llm.mock import MockLLMClient
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.runmgr import RunManager
    from cp.tools.tool import Registry as ToolRegistry

    class _FailingLease:
        async def acquire(self, run_id):
            return False
        async def renew(self, run_id):
            return True
        async def release(self, run_id):
            pass

    sandbox = LocalSandboxExecutor(ToolRegistry())
    mgr = RunManager(ToolRegistry(), sandbox, RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([{"role": "assistant", "content": "should not run"}]),
                     run_lease=_FailingLease())
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "p.yaml"), "w", encoding="utf-8") as f:
        f.write("permissions: []\nmax_steps: 3\n")

    run = await mgr.submit("x", os.path.join(pol_dir, "p.yaml"), "")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if mgr.get(run.run_id).status == "ended":
            break
        await asyncio.sleep(0.01)

    ended = mgr.get(run.run_id)
    assert ended.status == "ended"
    assert ended.termination == "leased_elsewhere"
    assert "another replica" in ended.final_answer
    # run.ended 事件确实发了
    assert any(e.type == "run.ended" for e in ended.events)


async def test_runmgr_normal_run_with_real_lease_completes(fake_redis):
    """有真实 run_lease 时,正常 run 能 acquire->renew->release,顺利结束且释放租约。"""
    import asyncio
    import os
    import tempfile
    import time
    from cp.adapters.local_sandbox import LocalSandboxExecutor
    from cp.adapters.local_state import RedisStatePort
    from cp.llm.mock import MockLLMClient
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.runmgr import RunManager
    from cp.tools.tool import Registry as ToolRegistry

    sandbox = LocalSandboxExecutor(ToolRegistry())
    mgr = RunManager(ToolRegistry(), sandbox, RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([{"role": "assistant", "content": "done"}]),
                     run_lease=RedisRunLease(fake_redis))
    pol_dir = tempfile.mkdtemp()
    with open(os.path.join(pol_dir, "p.yaml"), "w", encoding="utf-8") as f:
        f.write("permissions: []\nmax_steps: 3\n")

    run = await mgr.submit("x", os.path.join(pol_dir, "p.yaml"), "")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if mgr.get(run.run_id).status == "ended":
            break
        await asyncio.sleep(0.01)

    ended = mgr.get(run.run_id)
    assert ended.status == "ended"
    assert ended.termination != "leased_elsewhere"
    # run 结束后租约已释放
    assert await mgr.run_lease.holder(run.run_id) is None
