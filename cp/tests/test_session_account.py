import pytest

from cp.session.account import Account, ResourceQuota, Usage, QuotaExceeded


def test_charge_under_limit_succeeds():
    a = Account(ResourceQuota(max_steps=3, max_tokens=100))
    a.charge(Usage(steps=1, tokens=10))
    a.charge(Usage(steps=1, tokens=10))
    assert a.used().steps == 2


def test_charge_over_steps_rejected():
    a = Account(ResourceQuota(max_steps=2, max_tokens=100))
    a.charge(Usage(steps=1))
    a.charge(Usage(steps=1))
    with pytest.raises(QuotaExceeded):
        a.charge(Usage(steps=1))


def test_charge_over_tokens_rejected():
    a = Account(ResourceQuota(max_steps=10, max_tokens=50))
    with pytest.raises(QuotaExceeded):
        a.charge(Usage(steps=1, tokens=60))
