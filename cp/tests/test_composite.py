import asyncio
from cp.adapters.local_state import RedisStatePort
from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.primitives.registry import PrimitiveContext
from cp.primitives.composite import spawn_agent, compress_context, generate_skill, handoff


class MockSandbox:
    async def create(self, config):
        return "sbx-mock"

    async def exec_action(self, sid, action):
        tool = action.get("tool", "")
        if tool == "fs_read":
            return {"data": {"content": "skill list"}}
        if tool == "fs_write":
            return {"data": {"bytes_written": 10}}
        return {"data": {}}

    async def destroy(self, sid):
        pass


async def test_spawn_agent_publishes_created_and_completed(fake_redis):
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(session=None, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=RedisStatePort(fake_redis))
    result = await spawn_agent(ctx, {"agent_type": "researcher", "prompt": "find x", "context_mode": "fresh"})
    assert result.status == "success"
    assert result.data["agent_type"] == "researcher"
    # pub.created 应在 Stream
    created = await fake_redis.xrange("agent.researcher.created")
    assert len(created) == 1
    # pub.completed 应在 Stream
    completed = await fake_redis.xrange("agent.researcher.completed")
    assert len(completed) == 1


async def test_compress_context_writes_summary_to_kv(fake_redis):
    state = RedisStatePort(fake_redis)
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(session=None, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=state)
    result = await compress_context(ctx, {"session_id": "s1", "history": ["msg1", "msg2"], "strategy": "summarize"})
    assert result.status == "success"
    assert "summary" in result.data
    # 摘要应写入 kv
    stored = await state.get_session("session/s1/context")
    assert stored is not None


async def test_generate_skill_writes_file_and_lists(fake_redis):
    state = RedisStatePort(fake_redis)
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(session=None, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=state)
    result = await generate_skill(ctx, {"skill_name": "analyzer", "session_history": "did stuff"})
    assert result.status == "success"
    assert result.data["skill_name"] == "analyzer"
    assert "skills_list" in result.data


async def test_handoff_reads_context_and_publishes(fake_redis):
    state = RedisStatePort(fake_redis)
    # 预置上下文
    await state.save_session("session/s1/context", {"value": "ctx data"})
    bus = RedisStreamMessageBus(fake_redis)
    ctx = PrimitiveContext(session=None, sandbox_id="sbx", sandbox=MockSandbox(), bus=bus, state=state)
    result = await handoff(ctx, {"from_agent": "a1", "to_agent": "a2", "session_id": "s1"})
    assert result.status == "success"
    assert result.data["context_transferred"] is True
    # pub.handoff 应在 Stream
    handoff_events = await fake_redis.xrange("agent.handoff")
    assert len(handoff_events) == 1


# ---------- T1: CompositePrimitive 适配器 + schemas() ----------
def test_composite_primitive_adapter_conforms_to_protocol():
    from cp.primitives.composite import CompositePrimitive, COMPOSITES
    from cp.resource import Resource
    func, schema = COMPOSITES["spawn_agent"]
    p = CompositePrimitive("spawn_agent", func, schema)
    assert p.name == "spawn_agent"
    assert p.schema()["name"] == "spawn_agent"
    assert p.permission_key({}) == Resource(type="composite", id="spawn_agent")


def test_register_composites_into_registry():
    from cp.primitives.composite import register_composites
    from cp.primitives.registry import PrimitiveRegistry
    reg = PrimitiveRegistry()
    register_composites(reg)
    names = set(reg.names())
    assert {"spawn_agent", "compress_context", "generate_skill", "handoff", "compose"}.issubset(names)
    schema_names = {s["name"] for s in reg.schemas()}
    assert "compose" in schema_names


# ---------- T5: compose 复合操作(pipeline/router) ----------
async def test_compose_pipeline(fake_redis):
    """compose pipeline:两个子 agent 顺序执行。"""
    from cp.primitives.composite import compose
    from cp.primitives.registry import PrimitiveContext
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.audit.ledger import Ledger
    from cp.llm.mock import MockLLMClient
    from cp.policy.policy import Policy
    from cp.sanitize.sanitizer import Sanitizer
    from cp.session.session import Session
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s1", "local", Policy(permissions=[], max_steps=5, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, bus=RedisStreamMessageBus(fake_redis),
                               llm=MockLLMClient([{"role": "assistant", "content": "sub-result"}]))
        result = await compose(ctx, {"pattern": "pipeline", "task": "do work",
                                     "sub_agents": [{"prompt": "step A"}, {"prompt": "step B"}]})
    assert result.status == "success"
    assert result.data["pattern"] == "pipeline"
    assert "stages" in result.data


async def test_compose_router(fake_redis):
    from cp.primitives.composite import compose
    from cp.primitives.registry import PrimitiveContext
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.audit.ledger import Ledger
    from cp.llm.mock import MockLLMClient
    from cp.policy.policy import Policy
    from cp.sanitize.sanitizer import Sanitizer
    from cp.session.session import Session
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        sess = Session.new("s2", "local", Policy(permissions=[], max_steps=5, max_tokens=1000),
                           Sanitizer.new_from_rules([]), Ledger(d + "/a.log"))
        ctx = PrimitiveContext(session=sess, bus=RedisStreamMessageBus(fake_redis),
                               llm=MockLLMClient([{"role": "assistant", "content": "par-result"}]))
        result = await compose(ctx, {"pattern": "router", "task": "parallel work",
                                     "sub_agents": [{"prompt": "A"}, {"prompt": "B"}]})
    assert result.status == "success"
    assert result.data["pattern"] == "router"
    assert "sub_results" in result.data


async def test_compose_unknown_pattern_returns_error(fake_redis):
    from cp.primitives.composite import compose
    from cp.primitives.registry import PrimitiveContext
    ctx = PrimitiveContext()
    result = await compose(ctx, {"pattern": "bogus", "task": "x", "sub_agents": []})
    assert result.status == "error"
    assert "unknown pattern" in result.error
