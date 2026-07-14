from typing import Any, Dict, List


class MockLLMClient:
    """测试用 mock LLM。按预设脚本返回响应(支持多轮)。
    每次调用返回 scripts[cursor],cursor 递增。"""

    def __init__(self, scripts: List[Dict[str, Any]]):
        self._scripts = scripts
        self._cursor = 0
        self.calls = []

    async def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict[str, Any]:
        self.calls.append(list(messages))
        if self._cursor >= len(self._scripts):
            return {"role": "assistant", "content": "[mock] done"}
        resp = self._scripts[self._cursor]
        self._cursor += 1
        return resp
