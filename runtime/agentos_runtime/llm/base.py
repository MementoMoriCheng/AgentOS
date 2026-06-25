from typing import Protocol


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """返回 assistant 消息 dict（可能含 tool_calls）。"""
        ...
