import json
from typing import Optional

from cp.auth.auth import Identity


class ApiKeyAuthPort:
    """Redis-backed AuthPort: 把 API key 映射到 Identity。

    key 形如 `api_key:{key}` -> JSON `{"tenant":..., "user":...}`。
    粗粒度权限：check_permission 恒 True（细粒度归 Gate）。
    """

    def __init__(self, redis):
        self._r = redis

    async def register_key(self, key: str, tenant: str, user: str) -> None:
        payload = json.dumps({"tenant": tenant, "user": user})
        await self._r.set(f"api_key:{key}", payload)

    async def authenticate(self, api_key: str) -> Optional[Identity]:
        if not api_key:
            return None
        raw = await self._r.get(f"api_key:{api_key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        data = json.loads(raw)
        return Identity(tenant=data["tenant"], user=data["user"])

    async def check_permission(self, tenant_id: str, agent_id: str, action: str) -> bool:
        return True
