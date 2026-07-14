from cp.adapters.local_state import RedisStatePort
from cp.checkpoint import Checkpoint, SessionSnapshot, rehydrate


async def test_save_and_load_latest(fake_redis):
    state = RedisStatePort(fake_redis)
    cp = Checkpoint(state)
    snap = SessionSnapshot(session_id="s1", policy_path="p.yaml", sanitization_path="s.yaml",
                           used_steps=3, used_tokens=500, step=3)
    await cp.save(snap)
    loaded = await cp.load_latest("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.used_steps == 3
    assert loaded.step == 3


async def test_load_latest_none_when_empty(fake_redis):
    cp = Checkpoint(RedisStatePort(fake_redis))
    assert await cp.load_latest("nope") is None


async def test_multiple_checkpoints_latest_wins(fake_redis):
    state = RedisStatePort(fake_redis)
    cp = Checkpoint(state)
    await cp.save(SessionSnapshot(session_id="s1", step=1, used_steps=1))
    await cp.save(SessionSnapshot(session_id="s1", step=2, used_steps=2))
    await cp.save(SessionSnapshot(session_id="s1", step=3, used_steps=3))
    loaded = await cp.load_latest("s1")
    assert loaded.step == 3
    assert loaded.used_steps == 3


async def test_load_at_specific_step(fake_redis):
    state = RedisStatePort(fake_redis)
    cp = Checkpoint(state)
    await cp.save(SessionSnapshot(session_id="s1", step=1, used_steps=1))
    await cp.save(SessionSnapshot(session_id="s1", step=2, used_steps=2))
    loaded = await cp.load_at("s1", 1)
    assert loaded.step == 1
    assert loaded.used_steps == 1


async def test_state_survives_new_instance(fake_redis):
    """约束6:控制面无状态。新 Checkpoint 实例(模拟重启)读回。"""
    state1 = RedisStatePort(fake_redis)
    await Checkpoint(state1).save(SessionSnapshot(session_id="s1", step=5, used_steps=5))
    state2 = RedisStatePort(fake_redis)
    loaded = await Checkpoint(state2).load_latest("s1")
    assert loaded.step == 5


async def test_rehydrate_rebuilds_session(fake_redis):
    """重水合:从快照重建 Gate/Account(用量恢复)。"""
    from cp.policy.policy import Policy, Rule
    from cp.sanitize.sanitizer import Sanitizer

    async def policy_loader(path):
        return Policy(permissions=[Rule("path", "examples/**", ["fs_read"])], max_steps=10, max_tokens=1000)

    async def sanitizer_loader(path):
        return Sanitizer.new_from_rules([])

    snap = SessionSnapshot(session_id="s1", policy_path="p.yaml", sanitization_path="s.yaml",
                           identity="alice", used_steps=4, used_tokens=200, step=4)
    rebuilt = await rehydrate(snap, policy_loader, sanitizer_loader)
    assert rebuilt["session_id"] == "s1"
    assert rebuilt["identity"] == "alice"
    assert rebuilt["step"] == 4
    # account 用量应恢复
    used = await rebuilt["account"].used()
    assert used.steps == 4
    assert used.tokens == 200
    # Gate/Sanitizer 重建
    assert rebuilt["gate"] is not None
    assert rebuilt["sanitizer"] is not None
