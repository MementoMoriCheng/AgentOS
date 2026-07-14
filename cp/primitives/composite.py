"""V2 ch23.5 复合操作:固定骨架的原语序列脚本。外层 1 调用 + 内层动态。
骨架(控制流)由代码保证;内容(数据流)动态。"""
from typing import Any, Dict

from cp.primitives.registry import PrimitiveContext, PrimitiveResult


async def spawn_agent(ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
    """spawn_agent:创建子 agent。骨架:pub(created)→session→子 ReAct→pub(completed)。
    像 OS fork()。Week 3 内层 ReAct 用 mock(单步);真实多步留 Week 4。"""
    agent_type = params.get("agent_type", "default")
    prompt = params.get("prompt", "")
    context_mode = params.get("context_mode", "fresh")
    # 骨架步骤1:pub agent.created
    if ctx.bus:
        await ctx.bus.publish(f"agent.{agent_type}.created",
                              {"agent_type": agent_type, "parent": getattr(ctx.session, "id", None)})
    # 骨架步骤2:子 agent ReAct(Week 3 mock:单步 llm)
    from cp.primitives.llm import LlmPrimitive
    llm = LlmPrimitive()
    child_result = await llm.execute(ctx, {"model": "mock", "messages": [{"role": "user", "content": prompt}]})
    # 骨架步骤3:pub agent.completed
    if ctx.bus:
        await ctx.bus.publish(f"agent.{agent_type}.completed",
                              {"agent_type": agent_type, "result": child_result.data.get("content", "")})
    return PrimitiveResult(status="success", data={
        "agent_type": agent_type, "context_mode": context_mode,
        "child_result": child_result.data,
    })


async def compress_context(ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
    """compress_context:压缩上下文。骨架:llm(摘要)→write(kv://session/context, 摘要)。"""
    session_id = params.get("session_id", "default")
    history = params.get("history", [])
    strategy = params.get("strategy", "summarize")
    # 骨架步骤1:llm 摘要
    from cp.primitives.llm import LlmPrimitive
    summary = await LlmPrimitive().execute(ctx, {
        "model": "mock",
        "messages": [{"role": "system", "content": "Summarize this conversation"},
                     {"role": "user", "content": str(history)[:500]}],
    })
    # 骨架步骤2:write 摘要到 kv
    from cp.primitives.write import WritePrimitive
    await WritePrimitive().execute(ctx, {
        "target": f"kv://session/{session_id}/context",
        "data": summary.data.get("content", ""),
    })
    return PrimitiveResult(status="success", data={
        "session_id": session_id, "strategy": strategy,
        "summary": summary.data.get("content", ""),
    })


async def generate_skill(ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
    """generate_skill:生成 skill 文件。骨架:llm(审查)→write(file)→read(list)。"""
    skill_name = params.get("skill_name", "unnamed")
    session_history = params.get("session_history", "")
    # 骨架步骤1:llm 审查并生成 skill
    from cp.primitives.llm import LlmPrimitive
    review = await LlmPrimitive().execute(ctx, {
        "model": "mock",
        "messages": [{"role": "system", "content": "Review session and generate a Skill"},
                     {"role": "user", "content": str(session_history)[:500]}],
    })
    skill_content = review.data.get("content", "")
    # 骨架步骤2:write skill 文件
    from cp.primitives.write import WritePrimitive
    await WritePrimitive().execute(ctx, {
        "target": f"file:///skills/{skill_name}.md",
        "data": skill_content,
    })
    # 骨架步骤3:read skill 列表(刷新)
    from cp.primitives.read import ReadPrimitive
    listing = await ReadPrimitive().execute(ctx, {"source": "file:///skills/"})
    return PrimitiveResult(status="success", data={
        "skill_name": skill_name, "skill_content": skill_content,
        "skills_list": listing.data,
    })


async def handoff(ctx: PrimitiveContext, params: Dict[str, Any]) -> PrimitiveResult:
    """handoff:agent 移交。骨架:read(kv://session/context)→pub(agent.handoff)。"""
    from_agent = params.get("from_agent", "")
    to_agent = params.get("to_agent", "")
    session_id = params.get("session_id", "default")
    # 骨架步骤1:read 当前上下文
    from cp.primitives.read import ReadPrimitive
    context_data = await ReadPrimitive().execute(ctx, {"source": f"kv://session/{session_id}/context"})
    # 骨架步骤2:pub handoff
    if ctx.bus:
        await ctx.bus.publish("agent.handoff", {
            "from": from_agent, "to": to_agent,
            "context": context_data.data.get("value"),
        })
    return PrimitiveResult(status="success", data={
        "from": from_agent, "to": to_agent,
        "context_transferred": context_data.data.get("value") is not None,
    })
