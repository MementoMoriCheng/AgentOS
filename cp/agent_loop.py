"""V2 ch27 Layer 1:大 ReAct 循环。
while not done: llm(推理) → 原语执行(经 PrimitiveExecutor)→ 观察 → 再 llm。"""
import json
from typing import Any, Dict, List

from cp.primitives.registry import PrimitiveContext


def _drain_inbox(ctx, messages):
    """把 ctx.inbox 各 topic 的未读消息作为 user 观察追加到 messages。
    每条消息只注入一次(pop 后清空)。"""
    if ctx is None or not hasattr(ctx, "inbox"):
        return
    for topic, msgs in list(ctx.inbox.items()):
        while msgs:
            msg = msgs.pop(0)
            messages.append({
                "role": "user",
                "content": f"[inbox:{topic}] {json.dumps(msg, default=str)}",
            })


async def run_agent_loop(
    task: str,
    llm,
    executor,
    sess,
    ctx: PrimitiveContext,
    primitive_schemas: List[Dict[str, Any]] = None,
    max_steps: int = 20,
    system_prompt: str = None,
    on_step=None,
    initial_messages: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Agent Loop。llm 推理 → 原语执行 → 观察 → 循环。
    executor 可以是 PrimitiveExecutor 或 None(无工具执行)。
    system_prompt:HarnessRouter 选的 profile prompt(可空,空用默认)。
    on_step:async (messages, step) 每步后调(Checkpoint 存)。
    initial_messages:恢复续跑时传入(可空)。
    返回 {final_answer, steps_used, termination}。"""
    sys_msg = system_prompt or (
        "You are an autonomous agent. You have access to primitives (tools). "
        "Call a tool to accomplish the task. When done, respond with plain text."
    )
    messages: List[Dict[str, Any]] = list(initial_messages) if initial_messages else [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    for step in range(max_steps):
        steps_used = step + 1
        # drain inbox:sub 收到的消息作为观察注入,本步 LLM 可见
        _drain_inbox(ctx, messages)
        assistant = await llm.chat(messages, primitive_schemas or [])
        messages.append(assistant)

        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            final_answer = assistant.get("content", "(no content)")
            if on_step:
                await on_step(messages, steps_used)
            break

        # 执行每个原语调用(经安全管道)
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except (json.JSONDecodeError, KeyError):
                args = {}
            if executor is not None:
                resp = await executor.call(sess, ctx, name, args)
                if resp.errored:
                    content = f"Error: {resp.message}"
                elif not resp.allowed:
                    content = resp.message
                else:
                    content = json.dumps(resp.result, default=str)
            else:
                content = "[no executor]"
            messages.append({
                "role": "tool", "tool_call_id": tc["id"], "name": name, "content": content,
            })
        if on_step:
            await on_step(messages, steps_used)
    else:
        termination = "step_limit"
        final_answer = f"Reached step limit ({max_steps})."
        if on_step:
            await on_step(messages, steps_used)

    return {"final_answer": final_answer, "steps_used": steps_used, "termination": termination}
