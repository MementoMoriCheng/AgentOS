import time


class AdaptiveRateLimiter:
    """自适应限流器：保守初值 + 遇 429 退避降速 + 成功恢复。

    选项 Z 实现：兼顾稳定（不撞墙）和适应（动态调整）。
    在 Runtime 侧实现（429 是 DeepSeek HTTP 响应，只有发起方感知）。
    """

    def __init__(self, initial_rpm: int = 30, min_rpm: int = 5,
                 base_backoff_sec: float = 1.0, max_rpm: int | None = None):
        self._rpm = float(initial_rpm)
        self._min_rpm = float(min_rpm)
        self._max_rpm = float(max_rpm if max_rpm else initial_rpm)
        self._base_backoff = base_backoff_sec
        self._backoff_until = 0.0
        self._consecutive_429 = 0

    def current_rpm(self) -> int:
        return int(self._rpm)

    def on_429(self):
        """收到 429 时：降速一半 + 设置指数退避冷却。"""
        self._rpm = max(self._min_rpm, self._rpm * 0.5)
        self._consecutive_429 += 1
        backoff = self._base_backoff * (2 ** (self._consecutive_429 - 1))
        self._backoff_until = time.monotonic() + backoff

    def on_success(self):
        """成功时：恢复到初值，清退避。"""
        self._rpm = self._max_rpm
        self._consecutive_429 = 0
        self._backoff_until = 0.0

    def should_wait(self) -> float:
        """返回距下次可以发请求还需等待的秒数（0 = 立即可发）。"""
        now = time.monotonic()
        if self._backoff_until > now:
            return self._backoff_until - now
        return 0.0

    def acquire(self):
        """阻塞直到允许发请求。调用方在发 LLM 请求前调。"""
        wait = self.should_wait()
        if wait > 0:
            time.sleep(wait)
