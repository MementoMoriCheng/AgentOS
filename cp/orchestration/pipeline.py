from typing import Any, Awaitable, Callable, Dict, List


async def run_pipeline(
    agents: List[Callable[[str], Awaitable[Dict[str, Any]]]],
    initial_task: str,
) -> Dict[str, Any]:
    """顺序编排(V2 ch10 Pipeline):agent A 输出 → agent B 输入 → ... → 最后输出。
    每个 agent 是 async (task) -> {final_answer, ...}。
    返回 {stages: [...], final: 最后一个的 final_answer}。"""
    current = initial_task
    stages = []
    for i, agent_fn in enumerate(agents):
        result = await agent_fn(current)
        stages.append({"agent_index": i, "input": current, "output": result})
        current = result.get("final_answer", "")
    return {"stages": stages, "final": stages[-1]["output"]["final_answer"] if stages else current}
