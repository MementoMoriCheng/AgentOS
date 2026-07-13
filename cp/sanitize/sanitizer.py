import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

_OMIT = object()  # redact 哨兵:Sanitize 检测到就跳过该字段(完全移除)


@dataclass
class FieldRule:
    name: str
    strategy: str  # mask | hash | redact
    keep_prefix: int = 0
    keep_suffix: int = 0


@dataclass
class FieldSanitization:
    """脱敏摘要的一条:字段名 + 策略,不含原始值。"""
    field: str
    strategy: str


@dataclass
class SanitizeResult:
    data: Dict[str, Any]
    summary: List[FieldSanitization] = field(default_factory=list)


class Sanitizer:
    """按字段名应用脱敏规则。规则只读,线程安全。"""

    def __init__(self, rules: Dict[str, FieldRule]):
        self.rules = rules

    @classmethod
    def new_from_rules(cls, rules: Optional[List[FieldRule]]) -> "Sanitizer":
        m = {}
        for r in (rules or []):
            m[r.name] = r
        return cls(m)

    @classmethod
    def load_from_file(cls, path: str) -> "Sanitizer":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.new_from_rules(
            [FieldRule(r["name"], r["strategy"], r.get("keep_prefix", 0), r.get("keep_suffix", 0))
             for r in data.get("fields", [])]
        )

    def sanitize(self, data: Dict[str, Any]) -> SanitizeResult:
        """对 data 中匹配规则的字段应用脱敏,返回新 data 与摘要(不改原 dict)。"""
        out: Dict[str, Any] = {}
        summary: List[FieldSanitization] = []
        for k, v in data.items():
            rule = self.rules.get(k)
            if rule is None:
                out[k] = v
                continue
            applied = self._apply(rule, v)
            summary.append(FieldSanitization(field=k, strategy=rule.strategy))
            if applied is _OMIT:
                continue  # redact:完全移除(摘要已记)
            out[k] = applied
        return SanitizeResult(data=out, summary=summary)

    def sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """便捷包装,仅返回 data。"""
        return self.sanitize(data).data

    def _apply(self, rule: FieldRule, v: Any) -> Any:
        if not isinstance(v, str):
            if rule.strategy == "hash":
                return _hash_value(v)
            return v
        if rule.strategy == "mask":
            return _mask_string(v, rule.keep_prefix, rule.keep_suffix)
        if rule.strategy == "hash":
            return _hash_string(v)
        if rule.strategy == "redact":
            return _OMIT
        return v


def _mask_string(s: str, keep_prefix: int, keep_suffix: int) -> str:
    if keep_prefix == 0 and keep_suffix == 0:
        return "***"
    if len(s) <= keep_prefix + keep_suffix:
        return "***"
    return s[:keep_prefix] + "*" * (len(s) - keep_prefix - keep_suffix) + s[len(s) - keep_suffix:]


def _hash_string(s: str) -> str:
    h = hashlib.sha256(s.encode()).hexdigest()
    return "h_" + h[:16]


def _hash_value(v: Any) -> str:
    return _hash_string(f"{v}")


def load_from_file(path: str) -> Sanitizer:
    """模块级便捷入口,委托给 Sanitizer.load_from_file。"""
    return Sanitizer.load_from_file(path)
