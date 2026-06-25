import json
import os

import grpc

from .pb import agentos_pb2 as pb
from .pb import agentos_pb2_grpc as pb_grpc


class KernelClient:
    """连 Kernel gRPC 服务的客户端。

    暴露 start_session 和 call_tool。Runtime 通过它把所有有副作用的操作委托给 Kernel。
    """

    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        self._channel = None
        self._stub = None

    def _ensure(self):
        if self._stub is None:
            # Windows 上 grpc 连 unix socket 需要 unix: 前缀；其它平台直接用路径。
            target = f"unix:{self._socket_path}" if os.name != "nt" else f"file://{self._socket_path}"
            self._channel = grpc.insecure_channel(target)
            grpc.channel_ready_future(self._channel).result(timeout=10)
            self._stub = pb_grpc.KernelStub(self._channel)

    def start_session(self, policy_path: str, sanitization_path: str) -> str:
        self._ensure()
        resp = self._stub.StartSession(pb.StartSessionRequest(
            policy_path=policy_path, sanitization_path=sanitization_path))
        return resp.session_id

    def call_tool(self, session_id: str, tool: str, params: dict) -> dict:
        self._ensure()
        params_json = json.dumps(params) if params else ""
        resp = self._stub.CallTool(
            pb.CallToolRequest(session_id=session_id, tool=tool, params_json=params_json))
        result = {}
        if resp.result_json:
            result = json.loads(resp.result_json)
        return {
            "allowed": resp.allowed,
            "errored": resp.errored,
            "message": resp.message,
            "result": result,
        }

    def emit_event(self, run_id: str, session_id: str, etype: str, payload: dict) -> None:
        """把推理事件灌进 Kernel 的事件枢纽（经 EmitRuntimeEvent RPC）。"""
        self._ensure()
        self._stub.EmitRuntimeEvent(pb.Event(
            type=etype, run_id=run_id, session_id=session_id,
            payload_json=json.dumps(payload) if payload else "",
        ))

    def close(self):
        if self._channel:
            self._channel.close()
