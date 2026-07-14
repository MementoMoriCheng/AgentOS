"""Week 7 T4: 崩溃后 checkpoint 恢复续跑。
预置 checkpoint(模拟崩溃前快照) → submit(固定 session_id) → rehydrate 续跑。"""
import asyncio
import os
import tempfile

from cp.adapters.local_state import RedisStatePort
from cp.checkpoint import Checkpoint, SessionSnapshot, rehydrate
from cp.llm.mock import MockLLMClient
from cp.policy.policy import Policy
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.registry import PrimitiveRegistry
from cp.sanitize.sanitizer import Sanitizer
from cp.server.runmgr import RunManager


class _Sbx:
    async def create(self, c): return "sbx"
    async def exec_action(self, s, a): return {"data": {}}
    async def destroy(self, s): pass


async def _pol_loader(p):
    return Policy(permissions=[], max_steps=5, max_tokens=1000)


async def _san_loader(p):
    return Sanitizer.new_from_rules([])


async def test_rehydrate_restores_usage_and_messages(fake_redis):
    """rehydrate 从快照恢复 account 用量、messages、step。"""
    state = RedisStatePort(fake_redis)
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(
        session_id="s2", identity="local", used_steps=3, used_tokens=42,
        messages=[{"role": "system", "content": "x"}], step=3))
    snap = await ckpt.load_latest("s2")
    restored = await rehydrate(snap, _pol_loader, _san_loader)
    assert restored["account"]._used.steps == 3
    assert restored["account"]._used.tokens == 42
    assert restored["step"] == 3
    assert restored["messages"][0]["role"] == "system"


async def test_submit_resumes_from_existing_checkpoint(fake_redis):
    """预置 checkpoint → submit(固定 session_id) → 续跑成功(步数 ≤ 剩余)。"""
    state = RedisStatePort(fake_redis)
    fixed_sid = "sess-resume-test"

    # 预置:跑了 2 步,有消息历史
    ckpt = Checkpoint(state)
    await ckpt.save(SessionSnapshot(
        session_id=fixed_sid, identity="local", used_steps=2, used_tokens=0,
        messages=[{"role": "system", "content": "sys"},
                  {"role": "user", "content": "task"},
                  {"role": "assistant", "content": "was working"}],
        step=2))

    mgr = RunManager(None, _Sbx(), state,
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([{"role": "assistant", "content": "resumed and done"}]))
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        with open(p, "w") as f:
            f.write("permissions: []\nmax_steps: 5\n")
        # 用固定 session_id 匹配预置 checkpoint
        run = await mgr.submit("task", p, "", max_steps=5, session_id=fixed_sid)
    for _ in range(100):
        if run.status == "ended":
            break
        await asyncio.sleep(0.02)
    assert run.status == "ended"
    assert run.termination != "crashed"
    assert run.session_id == fixed_sid


async def test_submit_no_checkpoint_starts_fresh(fake_redis):
    """无 checkpoint → 全新开始(session_id 自动生成)。"""
    state = RedisStatePort(fake_redis)
    mgr = RunManager(None, _Sbx(), state,
                     executor_factory=lambda b: PrimitiveExecutor(PrimitiveRegistry(), b),
                     llm=MockLLMClient([{"role": "assistant", "content": "fresh"}]))
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        with open(p, "w") as f:
            f.write("permissions: []\nmax_steps: 3\n")
        run = await mgr.submit("task", p, "")
    assert run.run_id.startswith("run-")
    assert run.session_id.startswith("sess-")
    for _ in range(100):
        if run.status == "ended":
            break
        await asyncio.sleep(0.02)
    assert run.status == "ended"
