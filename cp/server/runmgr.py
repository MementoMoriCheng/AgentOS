"""异步 Run Manager:管理 run 生命周期 + 事件收集。
每个 run 一个 InProcess audit bus 收集可观测事件;后台 asyncio task 跑 agent loop。

双总线设计(Week 6 T2 正确性修复):
  - audit_bus = InProcess():executor/pipeline 的审计/可观测事件(primitive.called/run.*)。1 参 publish(Event)。
  - msg_bus   = RedisStreamMessageBus(可空):ctx.bus,pub/sub/复合操作的 topic 消息。2 参 publish(topic, payload)。
此前 ctx.bus 被错设成 InProcess,导致 pub/sub 一调就崩(它们调 2 参 publish)。
"""
import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from cp.agent_loop import run_agent_loop
from cp.audit.ledger import Ledger
from cp.eventbus.bus import Event, InProcess
from cp.policy.policy import load_from_file as load_policy
from cp.primitives.registry import PrimitiveContext
from cp.sanitize.sanitizer import Sanitizer, load_from_file as load_sanitizer
from cp.server.serialize import event_to_agent_json
from cp.session.session import Session
from cp.tools.tool import Registry


@dataclass
class Run:
    run_id: str
    session_id: str
    task: str
    status: str = "running"  # running | ended
    started_at: float = field(default_factory=time.time)
    events: List[Event] = field(default_factory=list)
    final_answer: str = ""
    termination: str = ""
    subscribers: List["asyncio.Queue"] = field(default_factory=list)


def _tenant_policy_path(policy_path: str, identity) -> str:
    """按 identity.tenant 选租户专属 policy(若存在)。

    租户隔离 = 不同租户用不同 policy 文件,路径白名单天然隔离。
    default/空 tenant 用原 policy_path。
    """
    if identity is None or not identity.tenant or identity.tenant == "default":
        return policy_path
    candidate = os.path.join(os.path.dirname(policy_path), f"{identity.tenant}.yaml")
    return candidate if os.path.exists(candidate) else policy_path


class RunManager:
    """管理 run:建 session → 后台跑 agent loop → 收集事件 → 标 ended。"""

    def __init__(self, registry: Registry, sandbox, state,
                 executor_factory: Optional[Callable] = None, llm=None,
                 audit_dir: str = "./audit",
                 msg_bus=None,            # 消息总线(pub/sub/复合操作用),None 时 ctx.bus=None
                 prim_registry=None,      # 用于 schemas() 喂给 LLM
                 scheduler=None,          # T4:并发限流
                 harness_router=None,     # T5:选 system_prompt
                 run_store=None,          # T6:Run 元数据/事件外部存储
                 run_lease=None,          # Week8:Run 执行租约(跨副本互斥)
                 audit_port=None):        # Week8:全局审计 sink(bus 事件 -> hash 链)
        self.registry = registry
        self.sandbox = sandbox
        self.state = state
        self.executor_factory = executor_factory  # (audit_bus) -> PrimitiveExecutor
        self.llm = llm
        self.audit_dir = audit_dir
        self.msg_bus = msg_bus
        self.prim_registry = prim_registry
        self.scheduler = scheduler
        self.harness_router = harness_router
        self.run_store = run_store
        self.run_lease = run_lease
        self.audit_port = audit_port
        self._runs: Dict[str, Run] = {}
        self._mu = asyncio.Lock()

    async def submit(self, task: str, policy_path: str, sanitization_path: str,
                     max_steps: int = 20, session_id: str = None, identity=None) -> Run:
        """提交 run。用构造时注入的 executor_factory + llm 跑 agent loop。
        session_id:固定会话 id(用于崩溃恢复:匹配已有 checkpoint 续跑)。"""
        policy_path = _tenant_policy_path(policy_path, identity)
        pol = load_policy(policy_path)
        sess_identity = identity.user if identity is not None else "local"
        tenant_id = identity.tenant if identity is not None else ""
        san = load_sanitizer(sanitization_path) if sanitization_path else Sanitizer.new_from_rules([])
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        if session_id is None:
            session_id = f"sess-{uuid.uuid4().hex[:8]}"

        # 检查是否有 checkpoint(崩溃恢复续跑)
        initial_messages = None
        os.makedirs(self.audit_dir, exist_ok=True)
        if self.state is not None:
            from cp.checkpoint import Checkpoint, rehydrate
            ckpt = Checkpoint(self.state)
            existing = await ckpt.load_latest(session_id)
            if existing is not None:
                async def _pol_loader(p): return pol
                async def _san_loader(p): return san
                restored = await rehydrate(existing, _pol_loader, _san_loader)
                sess = Session(
                    id=restored["session_id"], identity=restored["identity"],
                    policy=restored["policy"], gate=restored["gate"],
                    sanitizer=restored["sanitizer"], account=restored["account"],
                    ledger=Ledger(os.path.join(self.audit_dir, f"{session_id}.log")),
                )
                initial_messages = restored["messages"]
                remaining = max(1, max_steps - restored["step"])
            else:
                sess = Session.new(session_id, sess_identity, pol, san,
                                   Ledger(os.path.join(self.audit_dir, f"{session_id}.log")),
                                   tenant_id=tenant_id)
                remaining = max_steps
        else:
            sess = Session.new(session_id, sess_identity, pol, san,
                               Ledger(os.path.join(self.audit_dir, f"{session_id}.log")),
                               tenant_id=tenant_id)
            remaining = max_steps

        audit_bus = InProcess()  # 审计/可观测事件(executor/pipeline 用,1 参 publish)
        sandbox_id = await self.sandbox.create({"workspace": "."})

        executor = self.executor_factory(audit_bus) if self.executor_factory else None
        ctx = PrimitiveContext(
            session=sess, sandbox_id=sandbox_id, sandbox=self.sandbox,
            bus=self.msg_bus,  # 关键:ctx.bus = 消息总线(2 参 publish);None 时 pub/sub 报错
            state=self.state, run_id=run_id, llm=self.llm,
        )

        schemas = self.prim_registry.schemas() if self.prim_registry else []
        system_prompt = self._select_system_prompt(task)
        on_step = self._make_on_step(session_id, sess)

        run = Run(run_id=run_id, session_id=session_id, task=task)

        async def _collector(e: Event):
            run.events.append(e)
            if self.run_store:
                await self.run_store.append_event(run_id, event_to_agent_json(e))
            for q in list(run.subscribers):
                try:
                    q.put_nowait(e)
                except asyncio.QueueFull:
                    pass

        audit_bus.subscribe(_collector)
        # 全局审计 sink:每条事件旁路记入 hash 链 ledger(Week8 安全闭环)
        if self.audit_port is not None:
            _audit_port = self.audit_port

            async def _audit_sink(e: Event):
                await _audit_port.record(event_to_agent_json(e))
            audit_bus.subscribe(_audit_sink)

        async with self._mu:
            self._runs[run_id] = run
        if self.run_store:
            await self.run_store.save_meta(run_id, {
                "run_id": run_id, "session_id": session_id, "task": task,
                "status": "running", "started_at": run.started_at,
            })

        await audit_bus.publish(Event(type="run.started", session_id=session_id, run_id=run_id,
                                      payload={"task": task, "max_steps": remaining}))
        asyncio.create_task(self._run_agent(run, sess, ctx, executor, audit_bus,
                                            schemas, system_prompt, on_step, remaining,
                                            initial_messages))
        return run

    async def _run_agent(self, run: Run, sess: Session, ctx: PrimitiveContext, executor,
                         audit_bus: InProcess, schemas, system_prompt, on_step, max_steps: int,
                         initial_messages=None):
        # 执行租约:只有一个副本能跑(Week8 约束6)。拿不到 -> 标 leased_elsewhere 不执行。
        if self.run_lease is not None:
            if not await self.run_lease.acquire(run.run_id):
                run.termination = "leased_elsewhere"
                run.final_answer = "run is being executed by another replica"
                await self._finalize(run, audit_bus)
                return
            # 续租心跳:包装 on_step,每步续租(无论是否另存 checkpoint 的 on_step)
            _orig_on_step = on_step

            async def _on_step_with_lease(messages, step):
                await self.run_lease.renew(run.run_id)
                if _orig_on_step is not None:
                    await _orig_on_step(messages, step)
            on_step = _on_step_with_lease

        release = await self.scheduler.acquire() if self.scheduler else None
        try:
            result = await run_agent_loop(
                run.task, self.llm, executor, sess, ctx,
                primitive_schemas=schemas,
                system_prompt=system_prompt,
                on_step=on_step,
                max_steps=max_steps,
                initial_messages=initial_messages,
            )
            run.final_answer = result["final_answer"]
            run.termination = result["termination"]
        except Exception as e:  # noqa: BLE001 - 任何异常都标 crashed 并发 run.ended
            run.termination = "crashed"
            run.final_answer = f"error: {e}"
        finally:
            if release:
                release()
            if self.run_lease is not None:
                await self.run_lease.release(run.run_id)
            await self._finalize(run, audit_bus)

    async def _finalize(self, run: Run, audit_bus: InProcess) -> None:
        """收尾:发 run.ended + 存 meta + 标 ended。正常结束与 leased_elsewhere 共用。"""
        await audit_bus.publish(Event(
            type="run.ended", session_id=run.session_id, run_id=run.run_id,
            payload={"termination": run.termination, "final_answer": run.final_answer},
        ))
        if self.run_store:
            await self.run_store.save_meta(run.run_id, {
                "run_id": run.run_id, "session_id": run.session_id, "task": run.task,
                "status": "ended", "started_at": run.started_at,
                "final_answer": run.final_answer, "termination": run.termination,
            })
        run.status = "ended"

    def _select_system_prompt(self, task: str) -> Optional[str]:
        """T5:HarnessRouter 按 task_keywords 选 profile 的 system_prompt。"""
        if not self.harness_router:
            return None
        profile = self.harness_router.route(task)
        if profile and profile.system_prompt_template:
            return profile.system_prompt_template
        return None

    def _make_on_step(self, session_id: str, sess: Session):
        """T3:每步存 checkpoint。返回 async on_step(messages, step) 或 None。"""
        if self.state is None:
            return None
        from cp.checkpoint import Checkpoint, SessionSnapshot
        ckpt = Checkpoint(self.state)

        async def _on_step(messages, step):
            snap = SessionSnapshot(
                session_id=session_id,
                identity=sess.identity,
                used_steps=sess.account._used.steps,
                used_tokens=sess.account._used.tokens,
                messages=list(messages), step=step,
            )
            await ckpt.save(snap)
        return _on_step

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def list_runs(self) -> List[Run]:
        return list(self._runs.values())

    def subscribe(self, run_id: str) -> "asyncio.Queue":
        """订阅某 run 的实时事件。返回 Queue(只收订阅后产生的事件)。"""
        run = self._runs.get(run_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        if run is not None:
            run.subscribers.append(q)
        return q

    def unsubscribe(self, run_id: str, q: "asyncio.Queue"):
        run = self._runs.get(run_id)
        if run and q in run.subscribers:
            run.subscribers.remove(q)
