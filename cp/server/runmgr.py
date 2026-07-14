"""异步 Run Manager:管理 run 生命周期 + 事件收集。
每个 run 一个 InProcess bus 收集事件;后台 asyncio task 跑 agent loop。
WS 端点补播历史(run.events) + 实时推送(subscriber queue)。"""
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


class RunManager:
    """管理 run:建 session → 后台跑 agent loop → 收集事件 → 标 ended。"""

    def __init__(self, registry: Registry, sandbox, state,
                 executor_factory: Optional[Callable] = None, llm=None,
                 audit_dir: str = "./audit"):
        self.registry = registry
        self.sandbox = sandbox
        self.state = state
        self.executor_factory = executor_factory  # (bus) -> PrimitiveExecutor
        self.llm = llm
        self.audit_dir = audit_dir
        self._runs: Dict[str, Run] = {}
        self._mu = asyncio.Lock()

    async def submit(self, task: str, policy_path: str, sanitization_path: str,
                     max_steps: int = 20) -> Run:
        """提交 run。用构造时注入的 executor_factory + llm 跑 agent loop。"""
        pol = load_policy(policy_path)
        san = load_sanitizer(sanitization_path) if sanitization_path else Sanitizer.new_from_rules([])
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

        os.makedirs(self.audit_dir, exist_ok=True)
        ledger = Ledger(os.path.join(self.audit_dir, f"{session_id}.log"))
        sess = Session.new(session_id, "local", pol, san, ledger)

        bus = InProcess()
        sandbox_id = await self.sandbox.create({"workspace": "."})

        executor = self.executor_factory(bus) if self.executor_factory else None
        ctx = PrimitiveContext(
            session=sess, sandbox_id=sandbox_id, sandbox=self.sandbox,
            bus=bus, state=self.state, run_id=run_id,
        )

        run = Run(run_id=run_id, session_id=session_id, task=task)

        # 事件收集器:订阅 bus,追加到 run.events,推给 WS 订阅者
        async def _collector(e: Event):
            run.events.append(e)
            for q in list(run.subscribers):
                try:
                    q.put_nowait(e)
                except asyncio.QueueFull:
                    pass

        bus.subscribe(_collector)

        async with self._mu:
            self._runs[run_id] = run

        await bus.publish(Event(type="run.started", session_id=session_id, run_id=run_id,
                                payload={"task": task, "max_steps": max_steps}))

        asyncio.create_task(self._run_agent(run, sess, ctx, executor, bus, max_steps))
        return run

    async def _run_agent(self, run: Run, sess: Session, ctx: PrimitiveContext,
                         executor, bus: InProcess, max_steps: int):
        try:
            result = await run_agent_loop(run.task, self.llm, executor, sess, ctx, [], max_steps)
            run.final_answer = result["final_answer"]
            run.termination = result["termination"]
            await bus.publish(Event(
                type="run.ended", session_id=run.session_id, run_id=run.run_id,
                payload={"termination": run.termination, "final_answer": run.final_answer},
            ))
        except Exception as e:  # noqa: BLE001 - 任何异常都标 crashed 并发 run.ended
            run.termination = "crashed"
            run.final_answer = f"error: {e}"
            await bus.publish(Event(
                type="run.ended", session_id=run.session_id, run_id=run.run_id,
                payload={"termination": "crashed", "final_answer": run.final_answer},
            ))
        finally:
            run.status = "ended"

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
