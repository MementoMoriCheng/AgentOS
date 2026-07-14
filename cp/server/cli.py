"""CLI 入口:python -m cp.server.cli serve [--host] [--port] [--redis-url] [--llm mock|real]
                  [--auth api_key|none] [--api-key KEY:TENANT:USER ...]

启动 AgentOS 控制面 HTTP 服务。默认 fakeredis + mock LLM + API key 认证(开发用 dev-key)。
生产:--redis-url redis://... --llm real(需 DEEPSEEK_API_KEY)。"""
import argparse
import asyncio
import os


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


def build_app(redis, *, policy_dir: str = "examples/policies",
              sanitization_dir: str = "examples/sanitization",
              static_dir: str = "web-src/dist", llm_mode: str = "mock",
              max_concurrent: int = 10, auth_mode: str = "api_key",
              api_keys=None, audit_dir: str = "./audit"):
    """组装控制面 app(不启动 uvicorn)。注入消息总线 / run_store / 租约 / 认证 / 审计。

    auth_mode='api_key' 时启用 Bearer 认证;开发模式预置 dev-key(默认 tenant=default)。
    api_keys: [(key, tenant, user), ...] 覆盖默认 dev-key。
    返回 FastAPI app;mgr / audit_port 挂在 app.state 上(便于测试与运维)。
    """
    from cp.adapters.redis_bus import RedisStreamMessageBus
    from cp.audit.audit_port import LedgerAuditPort
    from cp.audit.ledger import Ledger
    from cp.auth.api_key import ApiKeyAuthPort
    from cp.compose import build_control_plane
    from cp.primitives.composite import register_composites
    from cp.primitives.executor import PrimitiveExecutor
    from cp.scheduler.scheduler import Scheduler
    from cp.server.app import create_app
    from cp.server.redis_store import RedisRunStore
    from cp.server.run_lease import RedisRunLease
    from cp.server.runmgr import RunManager

    cp = build_control_plane(redis)
    register_composites(cp["prim_registry"])
    msg_bus = RedisStreamMessageBus(redis)
    run_store = RedisRunStore(redis)
    run_lease = RedisRunLease(redis)
    os.makedirs(audit_dir, exist_ok=True)
    audit_port = LedgerAuditPort(Ledger(os.path.join(audit_dir, "server.log")))

    # 认证
    if auth_mode == "api_key":
        auth_port = ApiKeyAuthPort(redis)
        keys = list(api_keys) if api_keys else [("dev-key", "default", "developer")]

        async def _register():
            for key, tenant, user in keys:
                await auth_port.register_key(key, tenant, user)
        asyncio.run(_register())
    else:
        auth_port = None

    mgr = RunManager(
        cp["registry"], cp["sandbox"], cp["state"],
        executor_factory=lambda bus: PrimitiveExecutor(cp["prim_registry"], bus),
        llm=_make_llm(llm_mode),
        msg_bus=msg_bus,
        prim_registry=cp["prim_registry"],
        scheduler=Scheduler(max_concurrent),
        harness_router=cp["harness_router"],
        run_store=run_store,
        run_lease=run_lease,
        audit_port=audit_port,
    )
    app = create_app(mgr, policy_dir, sanitization_dir, static_dir,
                     run_store=run_store, auth_port=auth_port)
    app.state.mgr = mgr
    app.state.audit_port = audit_port
    if auth_port is not None:
        app.state.dev_keys = list(api_keys) if api_keys else [("dev-key", "default", "developer")]
    return app


def serve(host: str = "127.0.0.1", port: int = 8080, redis_url: str = "",
          policy_dir: str = "examples/policies", sanitization_dir: str = "examples/sanitization",
          static_dir: str = "web-src/dist", llm_mode: str = "mock", max_concurrent: int = 10,
          auth_mode: str = "api_key", api_keys=None):
    import uvicorn
    redis = _make_redis(redis_url)
    app = build_app(redis, policy_dir=policy_dir, sanitization_dir=sanitization_dir,
                    static_dir=static_dir, llm_mode=llm_mode, max_concurrent=max_concurrent,
                    auth_mode=auth_mode, api_keys=api_keys)
    dev = "auth=api_key, dev-key=dev-key" if auth_mode == "api_key" else "auth=none(dev)"
    print(f"AgentOS 控制面启动: http://{host}:{port} (llm={llm_mode}, max_concurrent={max_concurrent}, {dev})")
    uvicorn.run(app, host=host, port=port)


def _parse_api_key(spec: str):
    """'KEY:TENANT:USER' -> (key, tenant, user)。"""
    parts = spec.split(":")
    if len(parts) != 3:
        raise SystemExit(f"--api-key 需为 KEY:TENANT:USER 格式,得到: {spec!r}")
    return tuple(parts)


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
    s.add_argument("--auth", default="api_key", choices=["api_key", "none"],
                   help="api_key=Bearer 认证(开发预置 dev-key);none=不认证")
    s.add_argument("--api-key", action="append", default=[],
                   help="预置 API key,格式 KEY:TENANT:USER(可重复)")
    args = p.parse_args()
    if args.cmd == "serve":
        api_keys = [_parse_api_key(spec) for spec in args.api_key] or None
        serve(args.host, args.port, args.redis_url, args.policy_dir,
              args.sanitization_dir, args.static_dir, args.llm, args.max_concurrent,
              args.auth, api_keys)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
