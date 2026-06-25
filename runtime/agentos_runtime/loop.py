import json

from .tools import TOOL_SCHEMAS

SYSTEM_PROMPT = (
    "You are an autonomous agent running inside a sandboxed operating system. "
    "You have access to filesystem tools that are strictly permission-checked. "
    "If a tool returns 'permission denied', do not retry it; work around it or "
    "report the limitation. Complete the task using as few tool calls as possible, "
    "then give your final answer as plain text."
)


def run_agent(task: str, llm, kernel, session_id: str, run_id: str, max_steps: int = 20) -> str:
    """ReAct 循环。session 由调用方（网关）建立，loop 只用 session_id。

    发 run.started / runtime.step / run.ended。所有工具调用经 kernel（脱敏后结果才回）。
    遇 denied 不重试，遇 errored 回传给 LLM；未处理异常 → crashed。
    """
    kernel.emit_event(run_id=run_id, session_id=session_id, etype="run.started",
                      payload={"task": task, "max_steps": max_steps})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    try:
        for step in range(max_steps):
            steps_used = step + 1
            assistant = llm.chat(messages, TOOL_SCHEMAS)
            messages.append(assistant)

            tool_calls = assistant.get("tool_calls")
            if not tool_calls:
                # 没有工具调用 = 最终答案
                final_answer = assistant.get("content", "(no content)")
                break

            tool_call_summaries = [
                {"name": tc["function"]["name"],
                 "args": json.loads(tc["function"].get("arguments") or "{}")}
                for tc in tool_calls
            ]
            kernel.emit_event(run_id=run_id, session_id=session_id, etype="runtime.step",
                              payload={"step_index": step, "thought": assistant.get("content", ""),
                                       "tool_calls": tool_call_summaries})

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                res = kernel.call_tool(session_id, name, args)
                messages.append(_format_tool_result(tc["id"], name, res))
        else:
            termination = "step_limit"
            final_answer = f"Reached step limit ({max_steps}) without finishing."
    except Exception as exc:  # 任何未处理异常 → crashed
        termination = "crashed"
        final_answer = f"error: {exc}"
        raise
    finally:
        kernel.emit_event(run_id=run_id, session_id=session_id, etype="run.ended",
                          payload={"termination": termination, "steps_used": steps_used,
                                   "final_answer": final_answer})

    return final_answer


def _format_tool_result(tool_call_id: str, name: str, res: dict) -> dict:
    if res.get("errored"):
        content = f"Tool error: {res.get('message', 'unknown')}"
    elif not res.get("allowed"):
        # 注意：不回显拒绝的内部细节；kernel 已发通用消息。
        content = res.get("message", "permission denied")
    else:
        content = json.dumps(res.get("result", {}))
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
    }
