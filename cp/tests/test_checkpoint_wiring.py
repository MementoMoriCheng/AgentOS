"""Week 6 T3: Checkpoint 每步存 + 恢复续跑验证。
on_step 接线已在 runmgr(T2);这里直接测 Checkpoint + rehydrate + run_agent_loop 集成。"""
import os
import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.agent_loop import run_agent_loop
from cp.audit.ledger import Ledger
from cp.checkpoint import Checkpoint, SessionSnapshot, rehydrate
from cp.llm.mock import MockLLMClient
from cp.policy.policy import Policy
from cp.sanitize.sanitizer import Sanitizer
from cp.session.session import Session


async def _policy_loader(path):
    return Policy(permissions=[], max_steps=5, max_tokens=1000)


async def _san_loader(path):
    return Sanitizer.new_from_rules([])


async def test_checkpoint_saved_each_step(fake_redis):
    """每步后 on_step 存 checkpoint;load_latest 返回最新 step。"""
    state = RedisStatePort(fake_redis)
    ckpt = Checkpoint(state)
    saved = []

    async def on_step(messages, step):
        saved.append(step)
        await ckpt.save(SessionSnapshot(
            session_id="s1", used_steps=step, messages=list(messages), step=step))

    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local",
                           Policy(permissions=[], max_steps=5, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(os.path.join(d, "a.log")))
        llm = MockLLMClient([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "assistant", "content": "done"},
        ])
        # executor=None → tool 调用返回 [no executor],但仍推进两步
        await run_agent_loop("t", llm, None, sess, None, [], max_steps=3, on_step=on_step)
    assert saved == [1, 2]  # 两步各存一次
    snap = await ckpt.load_latest("s1")
    assert snap is not None
    assert snap.step == 2


async def test_rehydrate_resumes_usage(fake_redis):
    """rehydrate 从快照恢复 account 用量、messages、step。"""
    state = RedisStatePort(fake_redis)
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(
        session_id="s2", identity="local",
        used_steps=3, used_tokens=42,
        messages=[{"role": "system", "content": "x"}], step=3))
    snap = await ckpt.load_latest("s2")
    assert snap is not None
    restored = await rehydrate(snap, _policy_loader, _san_loader)
    assert restored["account"]._used.steps == 3
    assert restored["account"]._used.tokens == 42
    assert restored["messages"][0]["role"] == "system"
    assert restored["step"] == 3


async def test_runmgr_saves_checkpoint_each_step(fake_redis):
    """端到端:RunManager 跑 run → 每步存 checkpoint 到 RedisStatePort。"""
    from cp.primitives.executor import PrimitiveExecutor
    from cp.primitives.registry import PrimitiveRegistry
    from cp.server.runmgr import RunManager

    class _Sbx:
        async def create(self, c): return "sbx"
        async def exec_action(self, s, a): return {"data": {}}
        async def destroy(self, s): pass

    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, _Sbx(), state,
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([
                         {"role": "assistant", "content": "", "tool_calls": [
                             {"id": "1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                         {"role": "assistant", "content": "finished"}]),
                     prim_registry=PrimitiveRegistry())
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        with open(p, "w") as f:
            f.write("permissions: []\nmax_steps: 3\n")
        run = await mgr.submit("task", p, "")
        import asyncio
        for _ in range(100):
            if run.status == "ended":
                break
            await asyncio.sleep(0.02)
    # checkpoint 应已存(由 runmgr 的 on_step)
    ckpt = Checkpoint(state)
    snap = await ckpt.load_latest(run.session_id)
    assert snap is not None, "runmgr 未存 checkpoint"
    assert snap.step >= 1
    assert any(m["role"] == "system" for m in snap.messages)
