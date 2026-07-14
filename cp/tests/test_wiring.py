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


# ---------- T4: Scheduler 并发限流 ----------
async def test_scheduler_gates_concurrency(fake_redis):
    """Scheduler(max_concurrent=1) 让 3 个 run 串行执行(max_concurrent 永远≤1)。"""
    from cp.scheduler.scheduler import Scheduler

    class _SlowLLM:
        def __init__(self):
            self.entered = 0
            self.max_concurrent = 0

        async def chat(self, messages, tools=None):
            self.entered += 1
            self.max_concurrent = max(self.max_concurrent, self.entered)
            await asyncio.sleep(0.05)
            self.entered -= 1
            return {"role": "assistant", "content": "done"}

    slow = _SlowLLM()
    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=slow, scheduler=Scheduler(max_concurrent=1))
    p = _open_policy()
    runs = [await mgr.submit(f"t{i}", p, "") for i in range(3)]
    for _ in range(300):
        if all(r.status == "ended" for r in runs):
            break
        await asyncio.sleep(0.02)
    assert all(r.status == "ended" for r in runs)
    assert slow.max_concurrent == 1  # 串行,并发槽=1


# ---------- T5: HarnessRouter 选 system_prompt ----------
async def test_harness_router_selects_prompt(fake_redis):
    """任务含 'implement' → coder profile 的 system_prompt;纯任务 → generic。"""
    from cp.harness.profile import HarnessProfile
    from cp.harness.router import HarnessRouter

    def _make_router():
        r = HarnessRouter()
        r.register(HarnessProfile(name="coder", system_prompt_template="YOU ARE A CODER",
                                  task_keywords=["code", "implement"]), is_default=False)
        r.register(HarnessProfile(name="generic", system_prompt_template="GENERIC"), is_default=True)
        return r

    seen = {}

    class _SpyLLM:
        async def chat(self, messages, tools=None):
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
            seen["sys"] = sys_msg
            return {"role": "assistant", "content": "done"}

    # 任务含 implement → coder
    mgr = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=_SpyLLM(), harness_router=_make_router())
    p = _open_policy()
    run = await mgr.submit("implement a function", p, "")
    for _ in range(100):
        if run.status == "ended":
            break
        await asyncio.sleep(0.02)
    assert seen["sys"] == "YOU ARE A CODER"

    # 纯任务 → generic(默认)
    seen.clear()
    mgr2 = RunManager(None, _Sbx(), RedisStatePort(fake_redis),
                      executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                      llm=_SpyLLM(), harness_router=_make_router())
    run2 = await mgr2.submit("hello world", p, "")
    for _ in range(100):
        if run2.status == "ended":
            break
        await asyncio.sleep(0.02)
    assert seen["sys"] == "GENERIC"
