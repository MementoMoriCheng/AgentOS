import asyncio
from cp.orchestration.pipeline import run_pipeline
from cp.orchestration.router import run_router


async def _make_agent(answer_template: str):
    """造一个 mock agent:返回 final_answer = template + 输入。"""
    async def agent(task: str) -> dict:
        return {"final_answer": f"{answer_template}({task})", "steps_used": 1, "termination": "completed"}
    return agent


async def test_pipeline_sequential_chain():
    a = await _make_agent("A")
    b = await _make_agent("B")
    c = await _make_agent("C")
    result = await run_pipeline([a, b, c], "start")
    # A 收到 "start",输出 "A(start)";B 收到 "A(start)",输出 "B(A(start))";...
    assert result["final"] == "C(B(A(start)))"
    assert len(result["stages"]) == 3
    assert result["stages"][0]["input"] == "start"
    assert result["stages"][1]["input"] == "A(start)"


async def test_pipeline_single_agent():
    a = await _make_agent("solo")
    result = await run_pipeline([a], "task")
    assert result["final"] == "solo(task)"


async def test_pipeline_empty():
    result = await run_pipeline([], "task")
    assert result["final"] == "task"


async def test_router_parallel_runs_all():
    async def agent1(task):
        await asyncio.sleep(0.01)
        return {"final_answer": f"r1({task})"}
    async def agent2(task):
        return {"final_answer": f"r2({task})"}
    result = await run_router([agent1, agent2], "task")
    assert len(result["sub_results"]) == 2
    assert "r1" in result["final"]
    assert "r2" in result["final"]


async def test_router_with_aggregator():
    async def agent1(task):
        return {"final_answer": "alpha", "val": 1}
    async def agent2(task):
        return {"final_answer": "beta", "val": 2}

    async def agg(results):
        total = sum(r.get("val", 0) for r in results)
        return {"final_answer": f"sum={total}"}

    result = await run_router([agent1, agent2], "task", aggregator=agg)
    assert result["final"] == "sum=3"


async def test_router_parallelism_is_concurrent():
    """验证 agents 确实并行(总时间 ≈ max 而非 sum)。"""
    async def slow(task):
        await asyncio.sleep(0.1)
        return {"final_answer": "slow"}
    async def fast(task):
        await asyncio.sleep(0.1)
        return {"final_answer": "fast"}
    import time
    start = time.monotonic()
    await run_router([slow, fast], "task")
    elapsed = time.monotonic() - start
    # 并行:~0.1s;串行会 ~0.2s。留余量。
    assert elapsed < 0.18, f"expected parallel (~0.1s), got {elapsed:.2f}s"
