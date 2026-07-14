import os

from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.adapters.local_state import RedisStatePort
from cp.eventbus.bus import InProcess
from cp.harness.profile import load_profile
from cp.harness.router import HarnessRouter
from cp.pipeline.pipeline import Pipeline
from cp.primitives.exec import ExecPrimitive
from cp.primitives.executor import PrimitiveExecutor
from cp.primitives.io import IoPrimitive
from cp.primitives.llm import LlmPrimitive
from cp.primitives.pub import PubPrimitive
from cp.primitives.read import ReadPrimitive
from cp.primitives.registry import PrimitiveContext, PrimitiveRegistry
from cp.primitives.sub import SubPrimitive
from cp.primitives.write import WritePrimitive
from cp.tools.fs_tools import FSListTool, FSReadTool, FSWriteTool
from cp.tools.tool import Registry


def build_control_plane(redis, harness_dir: str = "examples/harness"):
    """组装完整控制面:Port 适配器 + 原语层 + Harness 适配器。
    开发用 fakeredis,生产换真实 Redis——代码零改。"""
    # 工具层(legacy fs 工具)
    registry = Registry()
    for t in [FSReadTool(), FSWriteTool(), FSListTool()]:
        registry.register(t)
    bus = InProcess()
    sandbox = LocalSandboxExecutor(registry)
    state = RedisStatePort(redis)
    pipe = Pipeline(registry, bus, sandbox)
    # 原语层(7 原子原语)
    prim_registry = PrimitiveRegistry()
    for p in [ExecPrimitive(), ReadPrimitive(), WritePrimitive(), LlmPrimitive(),
              IoPrimitive(), PubPrimitive(), SubPrimitive()]:
        prim_registry.register(p)
    prim_executor = PrimitiveExecutor(prim_registry, bus)
    # Harness 适配器层
    harness_router = HarnessRouter()
    if os.path.isdir(harness_dir):
        for fname in sorted(os.listdir(harness_dir)):
            if fname.endswith(".yaml"):
                profile = load_profile(os.path.join(harness_dir, fname))
                harness_router.register(profile, is_default=(fname == "generic.yaml"))
    return {
        "registry": registry, "bus": bus, "sandbox": sandbox, "state": state,
        "pipeline": pipe,
        "prim_registry": prim_registry, "prim_executor": prim_executor,
        "harness_router": harness_router,
    }


def make_primitive_context(cp_dict, session, sandbox_id):
    """构造原语执行上下文(注入 bus/state/sandbox)。bus 用 RedisStreamMessageBus
    需单独传入(因为它的生命周期要 start/stop)。"""
    return PrimitiveContext(
        session=session, sandbox_id=sandbox_id,
        sandbox=cp_dict["sandbox"], bus=None, state=cp_dict["state"],
    )
