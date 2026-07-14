import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional


async def run_router(
    agents: List[Callable[[str], Awaitable[Dict[str, Any]]]],
    task: str,
    aggregator: Optional[Callable[[List[Dict[str, Any]]], Awaitable[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """并行编排(V2 ch10 Router):多个 agent 并行跑同一任务;聚合结果。
    aggregator 是 async ([result1, result2, ...]) -> {final_answer, ...}。
    无 aggregator 时默认拼接。"""
    results = await asyncio.gather(*[agent_fn(task) for agent_fn in agents])
    results_list = list(results)
    if aggregator is not None:
        final = await aggregator(results_list)
    else:
        answers = [r.get("final_answer", "") for r in results_list]
        final = {"final_answer": " | ".join(answers), "sub_results": results_list}
    return {"sub_results": results_list, "final": final.get("final_answer", "")}
