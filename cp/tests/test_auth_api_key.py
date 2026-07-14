from cp.auth.api_key import ApiKeyAuthPort
from cp.auth.auth import Identity


async def test_register_and_authenticate(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    await auth.register_key("sk-test123", "acme", "alice")
    ident = await auth.authenticate("sk-test123")
    assert ident == Identity(tenant="acme", user="alice")


async def test_invalid_key_returns_none(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.authenticate("sk-bogus") is None


async def test_empty_key_returns_none(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.authenticate("") is None


async def test_check_permission_returns_true_for_known_tenant(fake_redis):
    auth = ApiKeyAuthPort(fake_redis)
    assert await auth.check_permission("acme", "agent1", "run") is True
