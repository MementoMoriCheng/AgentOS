"""Week 6 T2: 双总线接线 + schema 喂入验证。
关键正确性:ctx.bus=消息总线(2 参 publish)不再崩;LLM 收到原语 schema。"""
import asyncio
import os
import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.llm.mock import MockLLMClient
from cp.primitives.composite import register_composites
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.registry import PrimitiveRegistry
from cp.server.runmgr import RunManager


class _Sbx:
    async def create(self, c):
        return "sbx"

    async def exec_action(self, s, a):
        return {"data": {}}

    async def destroy(self, s):
        pass


def _open_policy():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "p.yaml")
    with open(p, "w") as f:
        f.write("permissions: []\nmax_steps: 3\n")
    return p


def _wait_ended(run, iters=100):
    import time
    for _ in range(iters):
        if run.status == "ended":
            return
        time.sleep(0.02)


async def test_llm_receives_primitive_schemas(fake_redis):
    """schemas 喂入 LLM:chat 的 tools 参数非空且含 spawn_agent。"""
    prim = PrimitiveRegistry()
    register_composites(prim)
    seen = {}

    class _SpyLLM:
        async def chat(self, messages, tools=None):
            seen.setdefault("tools", tools)

            class _Msg(dict):
                pass
            return {"role": "assistant", "content": "done"}

    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(prim, b), llm=_SpyLLM(),
                     msg_bus=RedisStreamMessageBus(fake_redis), prim_registry=prim)
    p = _open_policy()
    run = await mgr.submit("t", p, "")
    for _ in range(100):
        if run.status == "ended":
            break
        await asyncio.sleep(0.02)
    assert seen.get("tools"), "schemas 未喂入 LLM"
    assert any(s["name"] == "spawn_agent" for s in seen["tools"])


async def test_pub_primitive_does_not_crash_with_redis_bus(fake_redis):
    """ctx.bus 是 RedisStreamMessageBus 时,pub 原语 publish(topic,payload) 不崩。"""
    from cp.primitives.pub import PubPrimitive
    from cp.primitives.registry import PrimitiveContext
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(bus=bus)
    r = await PubPrimitive().execute(ctx, {"topic": "t.x", "payload": {"a": 1}})
    assert r.status == "success"
    assert len(await fake_redis.xrange("t.x")) == 1
