import os
import tempfile
from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.tools.tool import Registry
from cp.tools.fs_tools import FSReadTool, FSWriteTool


async def test_create_returns_sandbox_id():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({"workspace": "/tmp"})
    assert isinstance(sid, str) and sid.startswith("sbx-")


async def test_exec_action_runs_tool():
    reg = Registry()
    reg.register(FSWriteTool())
    reg.register(FSReadTool())
    ex = LocalSandboxExecutor(reg)
    sid = await ex.create({})
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            await ex.exec_action(sid, {"tool": "fs_write", "params": {"path": "wd/f.txt", "content": "hi"}})
            result = await ex.exec_action(sid, {"tool": "fs_read", "params": {"path": "wd/f.txt"}})
            assert result["data"]["content"] == "hi"
        finally:
            os.chdir(orig)


async def test_exec_unknown_tool_returns_error():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({})
    result = await ex.exec_action(sid, {"tool": "nope", "params": {}})
    assert "error" in result


async def test_exec_tool_raises_returns_error():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({})
    # fs_read on nonexistent path raises -> sandbox returns error dict
    result = await ex.exec_action(sid, {"tool": "fs_read", "params": {"path": "no_such_file.xyz"}})
    assert "error" in result


async def test_destroy():
    ex = LocalSandboxExecutor(Registry())
    sid = await ex.create({})
    await ex.destroy(sid)  # no exception
