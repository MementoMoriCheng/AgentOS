from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.adapters.local_state import RedisStatePort
from cp.eventbus.bus import InProcess
from cp.pipeline.pipeline import Pipeline
from cp.tools.fs_tools import FSListTool, FSReadTool, FSWriteTool
from cp.tools.tool import Registry


def build_control_plane(redis):
    """组装控制面:注入 Port 适配器。开发用 fakeredis,生产换真实 Redis。
    从 dev→prod 只换 redis 连接,代码零改(ch15 约束1/4)。"""
    registry = Registry()
    for t in [FSReadTool(), FSWriteTool(), FSListTool()]:
        registry.register(t)
    bus = InProcess()
    sandbox = LocalSandboxExecutor(registry)
    state = RedisStatePort(redis)
    pipe = Pipeline(registry, bus, sandbox)
    return {"registry": registry, "bus": bus, "sandbox": sandbox, "state": state, "pipeline": pipe}
