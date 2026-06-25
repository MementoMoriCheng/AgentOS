import os

from openai import OpenAI, RateLimitError

from ..rate_limit import AdaptiveRateLimiter
from .base import LLMClient


class DeepSeekClient:
    """DeepSeek，走 OpenAI 兼容 API，集成自适应限流。

    遇 429 自动退避重试（最多 3 次），由 AdaptiveRateLimiter 动态调速。
    """

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = None,
                 rate_limiter: AdaptiveRateLimiter | None = None):
        key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self._client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        self._model = model
        self._limiter = rate_limiter or AdaptiveRateLimiter(initial_rpm=30)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        # 遇 429 自适应退避重试，最多 3 次。
        for attempt in range(3):
            self._limiter.acquire()
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tools or None,
                )
                self._limiter.on_success()
                return self._to_dict(resp.choices[0].message)
            except RateLimitError:
                self._limiter.on_429()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def _to_dict(self, msg) -> dict:
        out = {"role": "assistant"}
        if msg.content:
            out["content"] = msg.content
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return out
