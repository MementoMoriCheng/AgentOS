from cp.adapters.local_sandbox import LocalSandboxExecutor
from cp.adapters.local_state import RedisStatePort
from cp.eventbus.bus import InProcess
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


def build_control_plane(redis):
    """组装控制面:注入 Port 适配器 + 原语层。开发用 fakeredis,生产换真实 Redis。"""
    registry = Registry()
    for t in [FSReadTool(), FSWriteTool(), FSListTool()]:
        registry.register(t)
    bus = InProcess()
    sandbox = LocalSandboxExecutor(registry)
    state = RedisStatePort(redis)
    pipe = Pipeline(registry, bus, sandbox)
    # 原语层
    prim_registry = PrimitiveRegistry()
    for p in [ExecPrimitive(), ReadPrimitive(), WritePrimitive(), LlmPrimitive(),
              IoPrimitive(), PubPrimitive(), SubPrimitive()]:
        prim_registry.register(p)
    prim_executor = PrimitiveExecutor(prim_registry, bus)
    return {
        "registry": registry, "bus": bus, "sandbox": sandbox, "state": state,
        "pipeline": pipe,
        "prim_registry": prim_registry, "prim_executor": prim_executor,
    }


def make_primitive_context(cp_dict, session, sandbox_id):
    """构造原语执行上下文(注入 bus/state/sandbox)。bus 用 RedisStreamMessageBus
    需单独传入(因为它的生命周期要 start/stop)。"""
    return PrimitiveContext(
        session=session, sandbox_id=sandbox_id,
        sandbox=cp_dict["sandbox"], bus=None, state=cp_dict["state"],
    )
