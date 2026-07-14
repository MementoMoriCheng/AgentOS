"""ch15 七约束可执行核对。Week 2 修复约束 1/3/4/5/6/7(约束2 Week1 已满足)。"""
import inspect

from cp.adapters.redis_bus import RedisStreamMessageBus
from cp.compose import build_control_plane
from cp.ports import SandboxPort, StatePort


async def test_constraint1_modules_behind_ports(fake_redis):
    """约束1:模块边界用接口。控制面组件是 Port 实例。"""
    cp = build_control_plane(fake_redis)
    assert isinstance(cp["state"], StatePort)
    assert isinstance(cp["sandbox"], SandboxPort)


async def test_constraint3_state_externalized(fake_redis):
    """约束3:状态在 Redis,不在进程内存。重启(新建实例)可恢复。"""
    cp = build_control_plane(fake_redis)
    await cp["state"].save_session("s1", {"used_steps": 7})
    cp2 = build_control_plane(fake_redis)
    got = await cp2["state"].get_session("s1")
    assert got == {"used_steps": 7}


async def test_constraint4_events_on_bus(fake_redis):
    """约束4:事件经消息总线(Redis Stream),持久化可 replay。"""
    bus = RedisStreamMessageBus(fake_redis)
    await bus.publish("agent_events.s1", {"type": "tool.called"})
    entries = await fake_redis.xrange("agent_events.s1")
    assert len(entries) == 1


async def test_constraint5_sandbox_remote_interface(fake_redis):
    """约束5:沙箱接口按远程设计(create/exec_action/destroy)。"""
    cp = build_control_plane(fake_redis)
    sid = await cp["sandbox"].create({"workspace": "/tmp"})
    assert sid.startswith("sbx-")
    result = await cp["sandbox"].exec_action(sid, {"tool": "fs_read", "params": {"path": "x"}})
    assert "data" in result or "error" in result
    await cp["sandbox"].destroy(sid)


async def test_constraint6_control_plane_stateless(fake_redis):
    """约束6:控制面无状态。两个实例共享同一 Redis,状态一致。"""
    cp1 = build_control_plane(fake_redis)
    cp2 = build_control_plane(fake_redis)
    await cp1["state"].save_session("s1", {"v": 1})
    assert (await cp2["state"].get_session("s1")) == {"v": 1}


def test_constraint7_orchestrator_no_direct_exec():
    """约束7:编排器(pipeline)不直接调 tool.execute,通过 sandbox.exec_action。"""
    from cp.pipeline.pipeline import Pipeline
    call_src = inspect.getsource(Pipeline.call)
    assert "sandbox.exec_action" in call_src, "pipeline must execute via sandbox"
    assert ".execute(" not in call_src, "pipeline.call must not call tool.execute directly"
