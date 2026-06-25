# 工具 schema，暴露给 LLM（function-calling 格式）。
# 注意：工具名用下划线，不是点号——函数名正则拒绝点号。
# 这些 schema 与 Go 侧 tools/fs_tools.go 的 Schema() 一一对应。
# 未来可从 Go 侧 Schema() 自动生成，消除手工同步漂移。

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "Read a text file. Path is relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": "Write text content to a file (creates parent dirs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": "List file names in a directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]
