import pytest
from cp.adapters.local_state import RedisStatePort
from cp.primitives.registry import PrimitiveRegistry, PrimitiveContext
from cp.primitives.exec import ExecPrimitive
from cp.primitives.read import ReadPrimitive
from cp.primitives.write import WritePrimitive
from cp.resource import Resource


class MockSandbox:
    """记录所有 exec_action 调用,按预设返回。"""
    def __init__(self):
        self.calls = []
        self.responses = {}  # (tool) -> result

    async def create(self, config):
        return "sbx-mock"

    async def exec_action(self, sid, action):
        self.calls.append(action)
        tool = action.get("tool", "")
        if tool in self.responses:
            return self.responses[tool]
        return {"data": {"mock": True}}

    async def destroy(self, sid):
        pass


def _ctx(sandbox, state=None):
    return PrimitiveContext(session=None, sandbox_id="sbx-mock", sandbox=sandbox, bus=None, state=state)


async def test_registry_register_and_get():
    reg = PrimitiveRegistry()
    reg.register(ExecPrimitive())
    p, ok = reg.get("exec")
    assert ok and p.name == "exec"
    _, ok = reg.get("nope")
    assert not ok


async def test_exec_calls_sandbox_shell():
    sb = MockSandbox()
    sb.responses["shell"] = {"data": {"stdout": "hello\n", "exit_code": 0}}
    prim = ExecPrimitive()
    result = await prim.execute(_ctx(sb), {"command": "echo hello"})
    assert result.status == "success"
    assert result.data["stdout"] == "hello\n"
    assert sb.calls[0]["tool"] == "shell"


async def test_exec_permission_key():
    pk = ExecPrimitive().permission_key({"command": "ls"})
    assert pk == Resource(type="shell", id="ls")


async def test_read_file_routes_to_fs_read():
    sb = MockSandbox()
    sb.responses["fs_read"] = {"data": {"content": "file contents"}}
    result = await ReadPrimitive().execute(_ctx(sb), {"source": "file:///workspace/x.txt"})
    assert result.status == "success"
    assert result.data["content"] == "file contents"
    assert sb.calls[0]["tool"] == "fs_read"


async def test_read_kv_routes_to_state(fake_redis):
    state = RedisStatePort(fake_redis)
    await state.save_session("mybucket/key1", {"value": "stored"})
    result = await ReadPrimitive().execute(_ctx(MockSandbox(), state), {"source": "kv://mybucket/key1"})
    assert result.status == "success"
    assert result.data["value"] == {"value": "stored"}


async def test_read_unsupported_scheme():
    result = await ReadPrimitive().execute(_ctx(MockSandbox()), {"source": "ftp://x"})
    assert result.status == "error"
    assert "unsupported" in result.error


async def test_write_file_routes_to_fs_write():
    sb = MockSandbox()
    sb.responses["fs_write"] = {"data": {"bytes_written": 5}}
    result = await WritePrimitive().execute(_ctx(sb), {"target": "file:///workspace/out.txt", "data": "hello"})
    assert result.status == "success"
    assert sb.calls[0]["tool"] == "fs_write"
    assert sb.calls[0]["params"]["content"] == "hello"


async def test_write_kv_routes_to_state(fake_redis):
    state = RedisStatePort(fake_redis)
    result = await WritePrimitive().execute(_ctx(MockSandbox(), state),
                                            {"target": "kv://ctx/data", "data": "myval"})
    assert result.status == "success"
    got = await state.get_session("ctx/data")
    assert got == {"value": "myval"}


async def test_read_permission_key_file():
    pk = ReadPrimitive().permission_key({"source": "file:///w/x.txt"})
    assert pk.type == "path"
    assert pk.id == "/w/x.txt"


async def test_write_permission_key_file():
    pk = WritePrimitive().permission_key({"target": "file:///w/y.txt"})
    assert pk.type == "path"
