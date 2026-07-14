import os
from typing import Any, Dict, List, Optional

try:
    from openai import AsyncOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


class AsyncDeepSeekClient:
    """DeepSeek async 客户端(OpenAI 兼容)。有 key 时真实调用。
    DeepSeek API: https://api.deepseek.com,模型 deepseek-chat。"""

    def __init__(self, model: str = "deepseek-chat", api_key: Optional[str] = None):
        if not _OPENAI_AVAILABLE:
            raise ImportError("openai package required: pip install openai")
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise ValueError("DEEPSEEK_API_KEY not set")
        self._client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
        self._model = model

    async def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        resp = await self._client.chat.completions.create(
            model=self._model, messages=messages, tools=tools or None,
        )
        msg = resp.choices[0].message
        out: Dict[str, Any] = {"role": "assistant"}
        if msg.content:
            out["content"] = msg.content
        if msg.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return out
