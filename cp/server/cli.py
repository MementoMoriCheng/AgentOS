"""CLI 入口:python -m cp.server.cli serve [--host] [--port] [--redis-url] [--llm mock|real]

启动 AgentOS 控制面 HTTP 服务。默认 fakeredis + mock LLM(本地开发零配置)。
生产:--redis-url redis://... --llm real(需 DEEPSEEK_API_KEY)。"""
import argparse


def _make_redis(url: str):
    if url:
        import redis.asyncio as aioredis
        return aioredis.from_url(url)
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis()


def _make_llm(mode: str):
    if mode == "real":
        from cp.llm.deepseek import AsyncDeepSeekClient
        return AsyncDeepSeekClient()
    from cp.llm.mock import MockLLMClient
    return MockLLMClient([{"role": "assistant", "content": "[server mock] done"}])


def serve(host: str = "127.0.0.1", port: int = 8080, redis_url: str = "",
          policy_dir: str = "examples/policies", sanitization_dir: str = "examples/sanitization",
          static_dir: str = "web-src/dist", llm_mode: str = "mock", max_concurrent: int = 10):
    import uvicorn
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.compose import build_control_plane
    from cp.primitives.composite import register_composites
    from cp.primitives.executor import PrimitiveExecutor
    from cp.scheduler.scheduler import Scheduler
    from cp.server.app import create_app
    from cp.server.redis_store import RedisRunStore
    from cp.server.runmgr import RunManager

    redis = _make_redis(redis_url)
    cp = build_control_plane(redis)
    # 注册复合操作到原语注册表(T1)
    register_composites(cp["prim_registry"])
    # 消息总线(T2:ctx.bus,pub/sub/复合操作用)
    msg_bus = RedisStreamMessageBus(redis)
    # Run 状态外部存储(T6:跨副本可观测)
    run_store = RedisRunStore(redis)
    mgr = RunManager(
        cp["registry"], cp["sandbox"], cp["state"],
        executor_factory=lambda bus: PrimitiveExecutor(cp["prim_registry"], bus),
        llm=_make_llm(llm_mode),
        msg_bus=msg_bus,
        prim_registry=cp["prim_registry"],
        scheduler=Scheduler(max_concurrent),
        harness_router=cp["harness_router"],
        run_store=run_store,
    )
    app = create_app(mgr, policy_dir, sanitization_dir, static_dir, run_store=run_store)
    print(f"AgentOS 控制面启动: http://{host}:{port} (llm={llm_mode}, max_concurrent={max_concurrent})")
    uvicorn.run(app, host=host, port=port)


def main():
    p = argparse.ArgumentParser(description="AgentOS control plane server")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="启动 HTTP 服务")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--redis-url", default="", help="空=fakeredis")
    s.add_argument("--policy-dir", default="examples/policies")
    s.add_argument("--sanitization-dir", default="examples/sanitization")
    s.add_argument("--static-dir", default="web-src/dist")
    s.add_argument("--llm", default="mock", choices=["mock", "real"])
    s.add_argument("--max-concurrent", type=int, default=10, help="并发 run 上限")
    args = p.parse_args()
    if args.cmd == "serve":
        serve(args.host, args.port, args.redis_url, args.policy_dir,
              args.sanitization_dir, args.static_dir, args.llm, args.max_concurrent)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
