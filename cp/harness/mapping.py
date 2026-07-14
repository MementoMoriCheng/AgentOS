"""V2 ch26 框架映射:把第三方框架的工具调用翻译成原语调用。
如 Claude 的 Bash(command)→ exec(command)。"""
from typing import Any, Dict, Tuple


def map_framework_call(profile, framework_tool: str, framework_args: Dict[str, Any]) -> Dict[str, Any]:
    """把框架工具调用映射成原语调用。
    返回 {primitive: str, params: dict};无映射时返回 {primitive: None}。"""
    template = profile.primitive_mappings.get(framework_tool)
    if template is None:
        return {"primitive": None, "params": {}}
    # 模板可能是纯原语名(如 "exec")或含参数插值(如 'read(source=file://{path})')
    primitive, params = _parse_template(template, framework_args)
    return {"primitive": primitive, "params": params}


def _parse_template(template: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """解析映射模板。两种形式:
    1. 纯原语名:"exec" → ("exec", framework_args)
    2. 含参数:'read(source=file://{path})' → ("read", {source: "file://"+args[path]})
    """
    template = template.strip()
    if "(" not in template:
        # 纯原语名:直接用 framework_args 作为 params
        return template, dict(args)
    # 解析 func(key=val,...) 形式
    paren = template.index("(")
    primitive = template[:paren].strip()
    body = template[paren + 1:].rstrip(")")
    params: Dict[str, Any] = {}
    if body:
        for pair in _split_pairs(body):
            key, val = pair.split("=", 1)
            key = key.strip()
            val = val.strip()
            params[key] = _interpolate(val, args)
    return primitive, params


def _split_pairs(body: str):
    """简单按逗号分割(不处理嵌套逗号;Week 4 MVP)。"""
    return [p.strip() for p in body.split(",") if p.strip()]


def _interpolate(val_template: str, args: Dict[str, Any]) -> str:
    """把 {key} 占位符替换成 args[key]。"""
    for k, v in args.items():
        val_template = val_template.replace("{" + k + "}", str(v))
    return val_template
