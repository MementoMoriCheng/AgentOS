from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Identity:
    tenant: str = "default"
    user: str = "local"
    tenant_id: str = ""  # 租户隔离用；空=不隔离（开发默认）


class Authenticator(Protocol):
    """验证调用方身份。MVP 用 LocalAuthenticator;未来加 mTLS/API key 是新实现。"""

    def authenticate(self, ctx: Any) -> Identity: ...


class LocalAuthenticator:
    """MVP 实现:不验证,返回固定 "local" 身份。
    前提:本机只有可信进程能连 socket(由 socket 权限保证)。"""

    def authenticate(self, ctx: Any) -> Identity:
        return Identity(tenant="default", user="local")
