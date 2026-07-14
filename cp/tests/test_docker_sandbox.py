import pytest
from cp.adapters.docker_sandbox import DockerExecutor, docker_available, DockerUnavailable

# 关键:无 Docker 时整个文件 skip,不阻塞 CI
pytestmark = pytest.mark.skipif(not docker_available(), reason="Docker daemon not available")


async def test_create_returns_sandbox_id():
    ex = DockerExecutor(image="python:3.11-slim")
    sid = await ex.create({})
    assert sid.startswith("sbx-docker-")
    await ex.destroy(sid)


async def test_exec_shell_command():
    ex = DockerExecutor(image="python:3.11-slim")
    sid = await ex.create({})
    try:
        result = await ex.exec_action(sid, {"tool": "shell", "params": {"command": "echo hello"}})
        assert "data" in result
        assert "hello" in result["data"]["stdout"]
        assert result["data"]["exit_code"] == 0
    finally:
        await ex.destroy(sid)


async def test_exec_unknown_tool_returns_error():
    ex = DockerExecutor(image="python:3.11-slim")
    sid = await ex.create({})
    try:
        result = await ex.exec_action(sid, {"tool": "fs_read", "params": {}})
        assert "error" in result
    finally:
        await ex.destroy(sid)


async def test_destroy_removes_container():
    ex = DockerExecutor(image="python:3.11-slim")
    sid = await ex.create({})
    await ex.destroy(sid)
    # 再次 destroy 不抛
    await ex.destroy(sid)


def test_docker_available_returns_bool():
    assert isinstance(docker_available(), bool)
