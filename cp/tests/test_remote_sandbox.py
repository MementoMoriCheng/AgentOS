import asyncio

from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.adapters.remote_sandbox import RemoteSandboxExecutor


async def test_exec_action_via_bus(fake_redis):
    """RemoteSandbox publish actions.{sid};模拟沙箱消费并回复 observations。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.start()
    try:
        sbx = RemoteSandboxExecutor(bus, timeout=3.0)
        sid = await sbx.create({"workspace": "."})

        # 模拟沙箱端:订阅 actions.{sid},收到 exec 后 publish observations 回复
        async def sandbox_handler(msg):
            if msg.get("op") == "exec":
                corr = msg["correlation_id"]
                await bus.publish("observations", {"correlation_id": corr,
                                                    "result": {"data": {"content": "hello"}}})
        bus.subscribe(f"actions.{sid}", sandbox_handler)

        result = await sbx.exec_action(sid, {"tool": "fs_read", "params": {"path": "x"}})
        assert result["data"]["content"] == "hello"
    finally:
        await bus.stop()


async def test_timeout_returns_error_when_no_sandbox(fake_redis):
    """无沙箱响应 -> 超时返回 error。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.start()
    try:
        sbx = RemoteSandboxExecutor(bus, timeout=0.3)
        sid = await sbx.create({})
        result = await sbx.exec_action(sid, {"tool": "x"})
        assert "error" in result
        assert "timeout" in result["error"]
    finally:
        await bus.stop()


async def test_remote_sandbox_satisfies_sandbox_port(fake_redis):
    """RemoteSandboxExecutor 实例 isinstance SandboxPort。"""
    from cp.ports import SandboxPort
    bus = RedisStreamMessageBus(fake_redis)
    sbx = RemoteSandboxExecutor(bus)
    assert isinstance(sbx, SandboxPort)
