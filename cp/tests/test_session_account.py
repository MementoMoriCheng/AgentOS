import pytest

from cp.session.account import Account, ResourceQuota, Usage, QuotaExceeded


async def test_charge_under_limit_succeeds():
    a = Account(ResourceQuota(max_steps=3, max_tokens=100))
    await a.charge(Usage(steps=1, tokens=10))
    await a.charge(Usage(steps=1, tokens=10))
    assert (await a.used()).steps == 2


async def test_charge_over_steps_rejected():
    a = Account(ResourceQuota(max_steps=2, max_tokens=100))
    await a.charge(Usage(steps=1))
    await a.charge(Usage(steps=1))
    with pytest.raises(QuotaExceeded):
        await a.charge(Usage(steps=1))


async def test_charge_over_tokens_rejected():
    a = Account(ResourceQuota(max_steps=10, max_tokens=50))
    with pytest.raises(QuotaExceeded):
        await a.charge(Usage(steps=1, tokens=60))
