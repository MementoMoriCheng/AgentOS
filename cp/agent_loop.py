"""V2 ch27 Layer 1:大 ReAct 循环。
while not done: llm(推理) → 原语执行(经 PrimitiveExecutor)→ 观察 → 再 llm。"""
import json
from typing import Any, Dict, List

from cp.primitives.registry import PrimitiveContext


async def run_agent_loop(
    task: str,
    llm,
    executor,
    sess,
    ctx: PrimitiveContext,
    primitive_schemas: List[Dict[str, Any]] = None,
    max_steps: int = 20,
) -> Dict[str, Any]:
    """Agent Loop。llm 推理 → 原语执行 → 观察 → 循环。
    executor 可以是 PrimitiveExecutor 或 None(无工具执行)。
    返回 {final_answer, steps_used, termination}。"""
    system_prompt = (
        "You are an autonomous agent. You have access to primitives (tools). "
        "Call a tool to accomplish the task. When done, respond with plain text."
    )
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    for step in range(max_steps):
        steps_used = step + 1
        assistant = await llm.chat(messages, primitive_schemas or [])
        messages.append(assistant)

        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            final_answer = assistant.get("content", "(no content)")
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
    else:
        termination = "step_limit"
        final_answer = f"Reached step limit ({max_steps})."

    return {"final_answer": final_answer, "steps_used": steps_used, "termination": termination}
