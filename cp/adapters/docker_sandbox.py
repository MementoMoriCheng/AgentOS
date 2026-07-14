"""DockerExecutor:SandboxPort 的 Docker 实现。真实 OS 级隔离(ch6)。
无 Docker daemon 时,创建实例抛 DockerUnavailable;测试用 skipif 守护。"""
import asyncio
from typing import Any, Dict, Optional

try:
    import docker
    from docker.errors import DockerException
    _DOCKER_AVAILABLE_LIB = True
except ImportError:
    _DOCKER_AVAILABLE_LIB = False
    DockerException = Exception


class DockerUnavailable(RuntimeError):
    """Docker daemon 不可用。"""


class DockerExecutor:
    """SandboxPort 的 Docker 实现。每个沙箱 = 一个容器(create 时启动,destroy 时删除)。
    exec_action 在容器内 docker exec。需要 Docker daemon 运行。"""

    def __init__(self, image: str = "python:3.11-slim", workdir: str = "/workspace"):
        if not _DOCKER_AVAILABLE_LIB:
            raise DockerUnavailable("docker-py not installed")
        self._image = image
        self._workdir = workdir
        self._client = None
        self._containers: Dict[str, Any] = {}  # sandbox_id -> container

    def _ensure_client(self):
        if self._client is None:
            try:
                self._client = docker.from_env()
                self._client.ping()  # 验证 daemon 在
            except DockerException as e:
                raise DockerUnavailable(f"cannot connect to Docker daemon: {e}")
        return self._client

    async def create(self, config: Dict[str, Any]) -> str:
        import uuid
        client = self._ensure_client()
        sid = f"sbx-docker-{uuid.uuid4().hex[:8]}"
        image = config.get("image", self._image)
        workdir = config.get("workdir", self._workdir)
        # 容器常驻,等 exec_action 时 docker exec
        loop = asyncio.get_event_loop()
        container = await loop.run_in_executor(None, lambda: client.containers.create(
            image, command="sleep infinity", detach=True, working_dir=workdir,
            tty=True,
        ))
        await loop.run_in_executor(None, container.start)
        self._containers[sid] = container
        return sid

    async def exec_action(self, sandbox_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        container = self._containers.get(sandbox_id)
        if container is None:
            return {"error": f"unknown sandbox: {sandbox_id}"}
        tool = action.get("tool", "")
        params = action.get("params", {})
        if tool == "shell":
            command = params.get("command", "")
            loop = asyncio.get_event_loop()
            exit_code, output = await loop.run_in_executor(None, self._exec_sync, container, command)
            return {"data": {"stdout": output, "exit_code": exit_code}}
        # 其它工具(fs_read/fs_write)在 Week 3 MVP 用 shell 模拟或拒绝
        return {"error": f"tool {tool} not supported in DockerExecutor (Week 3 MVP: shell only)"}

    def _exec_sync(self, container, command):
        result = container.exec_run(["sh", "-c", command])
        output = result.output.decode() if hasattr(result, "output") else str(result)
        exit_code = result.exit_code if hasattr(result, "exit_code") else 0
        return exit_code, output

    async def destroy(self, sandbox_id: str) -> None:
        container = self._containers.pop(sandbox_id, None)
        if container is not None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, container.stop)
            await loop.run_in_executor(None, container.remove)


def docker_available() -> bool:
    """检测 Docker daemon 是否可用(测试用 skipif 守护)。"""
    if not _DOCKER_AVAILABLE_LIB:
        return False
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False
