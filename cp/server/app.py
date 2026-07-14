"""FastAPI 应用:复刻旧 gateway 的 API 契约,前端零改对接。
端点见 web-src/src/lib/api.ts + gateway/internal/api/handlers.go。

有 run_store(RedisRunStore)时,list/get/WS 读外部存储——跨副本可观测(约束6)。
无 run_store 时,退回进程内 RunManager(单副本开发模式)。"""
import asyncio
import os
from typing import List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cp.server.runmgr import RunManager
from cp.server.serialize import event_to_agent_json


def create_app(mgr: RunManager, policy_dir: str, sanitization_dir: str,
               static_dir: Optional[str] = None, run_store=None, auth_port=None) -> FastAPI:
    app = FastAPI(title="AgentOS Control Plane")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # 默认无身份(开发模式);有 auth_port 时保护 /api/* HTTP 路由。
        # WS(/api/events)不经 HTTP 中间件,认证留后续。
        request.state.identity = None
        if auth_port is not None and request.url.path.startswith("/api/"):
            authz = request.headers.get("authorization", "")
            key = authz[len("Bearer "):].strip() if authz.startswith("Bearer ") else ""
            identity = await auth_port.authenticate(key) if key else None
            if identity is None:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            request.state.identity = identity
        return await call_next(request)

    @app.get("/api/policies")
    async def list_policies():
        return _scan_yaml(policy_dir)

    @app.get("/api/sanitizations")
    async def list_sanitizations():
        return _scan_yaml(sanitization_dir)

    @app.get("/api/runs")
    async def list_runs(id: Optional[str] = None):
        if id:
            if run_store:
                meta = await run_store.get_meta(id)
                if meta is None:
                    return JSONResponse({"error": "not found"}, status_code=404)
                events = await run_store.get_events(id)
                return {"run": meta, "events": events}
            run = mgr.get(id)
            if run is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return {
                "run": {
                    "run_id": run.run_id, "session_id": run.session_id,
                    "status": run.status, "task": run.task,
                    "started_at": run.started_at,
                },
                "events": [event_to_agent_json(e) for e in run.events],
            }
        if run_store:
            return await run_store.list_runs()
        return [
            {"run_id": r.run_id, "session_id": r.session_id, "status": r.status,
             "task": r.task, "started_at": r.started_at}
            for r in mgr.list_runs()
        ]

    @app.post("/api/runs")
    async def submit_run(body: dict, request: Request):
        identity = getattr(request.state, "identity", None)
        task = body.get("task", "")
        policy = _resolve(body.get("policy", ""), policy_dir)
        sanitization = _resolve(body.get("sanitization", ""), sanitization_dir)
        run = await mgr.submit(task, policy, sanitization, max_steps=20, identity=identity)
        return {"run_id": run.run_id, "session_id": run.session_id}

    @app.websocket("/api/events")
    async def events_ws(ws: WebSocket):
        await ws.accept()
        run_id = ws.query_params.get("run_id", "")

        if run_store:
            await _ws_via_store(ws, run_id, run_store)
        else:
            await _ws_via_queue(ws, run_id, mgr)

    # 静态前端(若 dist 已构建)
    if static_dir and os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


async def _ws_via_store(ws: WebSocket, run_id: str, run_store):
    """跨副本 WS:回放历史(LIST)+ 实时订阅(pub/sub channel)。"""
    # 补播历史
    for e in await run_store.get_events(run_id):
        await ws.send_json(e)
    meta = await run_store.get_meta(run_id)
    if meta and meta.get("status") == "ended":
        await ws.close()
        return
    # 实时:订阅 channel
    pubsub = run_store._r.pubsub()
    await pubsub.subscribe(run_store.channel(run_id))
    try:
        while True:
            msg = await pubsub.get_message(timeout=1.0)
            if msg and msg.get("type") == "message":
                raw = msg["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode()
                import json
                await ws.send_json(json.loads(raw))
                if json.loads(raw).get("type") == "run.ended":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(run_store.channel(run_id))
        await ws.close()


async def _ws_via_queue(ws: WebSocket, run_id: str, mgr: RunManager):
    """单副本 WS:回放历史(run.events)+ 实时订阅(subscriber queue)。"""
    run = mgr.get(run_id)
    if run is not None:
        for e in run.events:
            await ws.send_json(event_to_agent_json(e))
        if run.status == "ended":
            await ws.close()
            return
    q = mgr.subscribe(run_id)
    try:
        while True:
            try:
                e = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                continue
            await ws.send_json(event_to_agent_json(e))
            if e.type == "run.ended":
                break
    except WebSocketDisconnect:
        pass
    finally:
        mgr.unsubscribe(run_id, q)
        await ws.close()


def _scan_yaml(directory: str) -> List[str]:
    """扫描目录下的 *.yaml/*.yml,返回排序后的文件名列表(复刻旧 scanYaml)。"""
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(f for f in os.listdir(directory) if f.endswith(".yaml") or f.endswith(".yml"))


def _resolve(name: str, directory: str) -> str:
    """把提交的 policy/sanitization 名解析成完整路径(复刻旧 resolveFile)。
    若 name 已是路径(含分隔符或绝对路径)原样返回;否则在 directory 内查找。"""
    if not name:
        return name
    if os.path.sep in name or "/" in name or os.path.isabs(name):
        return name
    full = os.path.join(directory, name)
    return full if os.path.exists(full) else name
