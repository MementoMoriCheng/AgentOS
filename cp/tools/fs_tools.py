import asyncio
import json
import os
from typing import Any, Dict

from cp.resource import Resource
from cp.sandbox.fs import resolve
from cp.tools.tool import ToolResult


class FSReadTool:
    def name(self) -> str:
        return "fs_read"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_read",
            "description": "Read a text file. Path is relative to the workspace root.",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    async def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        content = await asyncio.to_thread(self._read_file, safe)
        return ToolResult(data={"content": content})

    def _read_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


class FSWriteTool:
    def name(self) -> str:
        return "fs_write"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_write",
            "description": "Write text content to a file (creates parent dirs).",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"},
                                          "content": {"type": "string"}},
                           "required": ["path", "content"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    async def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        content = params.get("content", "")
        await asyncio.to_thread(self._write_file, safe, content)
        return ToolResult(data={"bytes_written": len(content)})

    def _write_file(self, safe, content):
        os.makedirs(os.path.dirname(safe), exist_ok=True)
        # 原子写:先写 .tmp,再 rename。崩溃时要么旧要么新,无半成品。
        tmp = safe + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, safe)


class FSListTool:
    def name(self) -> str:
        return "fs_list"

    def schema(self) -> str:
        return json.dumps({
            "name": "fs_list",
            "description": "List file names in a directory.",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        })

    def permission_key(self, params: Dict[str, Any]) -> Resource:
        return Resource(type="path", id=params.get("path", ""))

    async def execute(self, ctx: Any, params: Dict[str, Any]) -> ToolResult:
        safe = resolve(params.get("path", ""))
        names = await asyncio.to_thread(self._list_dir, safe)
        return ToolResult(data={"entries": names})

    def _list_dir(self, path):
        return sorted(os.listdir(path))
