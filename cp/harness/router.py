from typing import Dict, List, Optional
from cp.harness.profile import HarnessProfile


class HarnessRouter:
    """V2 ch22.5 Harness Router:按任务类型路由到 Profile。
    代码任务→claude-style;默认→generic。"""

    def __init__(self):
        self._profiles: Dict[str, HarnessProfile] = {}
        self._default: Optional[HarnessProfile] = None

    def register(self, profile: HarnessProfile, is_default: bool = False) -> None:
        self._profiles[profile.name] = profile
        if is_default or self._default is None:
            self._default = profile

    def route(self, task: str) -> HarnessProfile:
        """根据任务文本匹配 Profile 的 task_keywords。"""
        task_lower = task.lower()
        best = None
        best_score = 0
        for profile in self._profiles.values():
            score = sum(1 for kw in profile.task_keywords if kw in task_lower)
            if score > best_score:
                best_score = score
                best = profile
        if best is not None and best_score > 0:
            return best
        return self._default
