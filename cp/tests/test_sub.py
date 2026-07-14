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


# ---------- T3: inbox drain into agent loop messages ----------
def test_drain_inbox_appends_user_observations():
    """_drain_inbox 把 inbox 消息作为 role=user 观察追加到 messages。"""
    from cp.agent_loop import _drain_inbox
    ctx = PrimitiveContext()
    ctx.inbox = {"updates": [{"x": 1}, {"x": 2}]}
    messages = [{"role": "system", "content": "sys"}]
    _drain_inbox(ctx, messages)
    assert len(messages) == 3  # 原 1 + 2 条 inbox
    assert messages[1]["role"] == "user"
    assert "[inbox:updates]" in messages[1]["content"]
    assert ctx.inbox["updates"] == []  # drained


def test_drain_inbox_no_ctx_is_noop():
    """ctx=None 时不崩。"""
    from cp.agent_loop import _drain_inbox
    messages = []
    _drain_inbox(None, messages)
    assert messages == []


async def test_inbox_message_visible_to_llm_in_loop():
    """端到端:inbox 有消息时,agent loop 下一步 LLM 能看到注入的观察。"""
    from cp.agent_loop import run_agent_loop
    from cp.primitives.registry import PrimitiveContext

    seen_messages = []

    class _SpyLLM:
        async def chat(self, messages, tools=None):
            seen_messages.append(list(messages))
            return {"role": "assistant", "content": "done"}

    ctx = PrimitiveContext()
    ctx.inbox = {"updates": [{"data": "hello"}]}
    await run_agent_loop("task", _SpyLLM(), None, None, ctx, [], max_steps=1)
    # 第一步 LLM 调用前,drain 把 inbox 消息注入了
    assert len(seen_messages) == 1
    assert any("[inbox:updates]" in m.get("content", "") for m in seen_messages[0])
