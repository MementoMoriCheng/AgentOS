import os
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class Rule:
    """一条权限规则:某资源类型 + glob 模式 + 允许的动作集合。"""
    resource_type: str
    pattern: str
    actions: List[str] = field(default_factory=list)


@dataclass
class Policy:
    """授予一个 agent 会话的完整策略。"""
    agent_role: str = ""
    permissions: List[Rule] = field(default_factory=list)
    sanitization_path: str = ""
    max_steps: int = 0
    max_tokens: int = 0


def load_from_file(path: str) -> Policy:
    """从 YAML 文件加载策略。max_steps 为 0 时默认 20。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    p = Policy(
        agent_role=data.get("agent_role", ""),
        permissions=[
            Rule(r["resource_type"], r["pattern"], r.get("actions", []))
            for r in data.get("permissions", [])
        ],
        sanitization_path=data.get("sanitization_path", ""),
        max_steps=data.get("max_steps", 0),
        max_tokens=data.get("max_tokens", 0),
    )
    if p.max_steps == 0:
        p.max_steps = 20
    return p
