import os
import re

from cp.policy.policy import Policy
from cp.resource import Resource


class Gate:
    """按 Policy 的规则匹配 (action, resource)。不认识任何工具名,只做通用三元匹配。"""

    def __init__(self, policy: Policy):
        self.rules = policy.permissions

    def allowed(self, action: str, res: Resource) -> bool:
        for rule in self.rules:
            if rule.resource_type != res.type:
                continue
            if action not in rule.actions:
                continue
            if _match_id(rule.pattern, rule.resource_type, res.id):
                return True
        return False


def _match_id(pattern: str, resource_type: str, id_: str) -> bool:
    """按资源类型决定匹配方式。path 类型:glob + 拒穿越/绝对路径;其它:精确匹配。"""
    if resource_type == "path":
        return _match_path(pattern, id_)
    return pattern == id_


def _match_path(pattern: str, path: str) -> bool:
    # 统一正斜杠,避免 Windows 反斜杠与 glob 不匹配
    clean = os.path.normpath(path).replace(os.sep, "/")
    pattern = os.path.normpath(pattern).replace(os.sep, "/")
    if os.path.isabs(path):
        return False
    if ".." in clean.split("/"):
        return False
    return re.fullmatch(_glob_to_regex(pattern), clean) is not None


def _glob_to_regex(pattern: str) -> str:
    """把含 ** 的 glob 翻译成正则。

    **  :跨目录段匹配(零或多个段);
    *   :段内匹配(不含 /);
    ?   :单个字符(不含 /)。
    """
    i = 0
    n = len(pattern)
    out = []
    while i < n:
        if pattern[i:i + 2] == "**":
            prev = pattern[i - 1] if i > 0 else ""
            nxt = pattern[i + 2] if i + 2 < n else ""
            if nxt == "" and prev == "/":
                # /** 在末尾:吸收前置的 /,匹配 (目录本身 | 目录/任意)
                if out and out[-1] == "/":
                    out.pop()
                out.append(r"(?:/.*)?")
                i += 2
            elif nxt == "/" and prev != "/" and prev != "":
                # **/ 在中间:零或多个段
                out.append(r"(?:.*/)?")
                i += 3
            else:
                out.append(r".*")
                i += 2
        elif pattern[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append(r"[^/]")
            i += 1
        elif pattern[i] == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)
