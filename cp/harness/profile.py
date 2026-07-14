from dataclasses import dataclass, field
from typing import Dict, List
import yaml


@dataclass
class HarnessProfile:
    """V2 ch22 Harness Profile:描述一个框架的编排风格 + 原语映射。
    加新框架 = 写一个 YAML(D016:不改核心原语/框架代码)。"""
    name: str
    description: str = ""
    system_prompt_template: str = ""
    safety_rules: List[str] = field(default_factory=list)
    primitive_mappings: Dict[str, str] = field(default_factory=dict)
    task_keywords: List[str] = field(default_factory=list)


def load_profile(path: str) -> HarnessProfile:
    """从 YAML 加载 Profile。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return HarnessProfile(
        name=data.get("name", "unnamed"),
        description=data.get("description", ""),
        system_prompt_template=data.get("system_prompt_template", ""),
        safety_rules=data.get("safety_rules", []),
        primitive_mappings=data.get("primitive_mappings", {}),
        task_keywords=data.get("task_keywords", []),
    )
