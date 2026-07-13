from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    """权限判定的泛化对象。type 决定匹配哪类规则(path/db_table/http_url...),id 是具体标识。"""
    type: str
    id: str
