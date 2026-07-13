import os
import tempfile

from cp.auth.auth import LocalAuthenticator
from cp.auth.policy_guard import is_trusted_policy


def test_local_authenticator_returns_local_identity():
    ident = LocalAuthenticator().authenticate(None)
    assert ident.tenant == "default"
    assert ident.user == "local"


def test_trusted_policy_inside_dir_allowed():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p.yaml")
        open(p, "w").close()
        assert is_trusted_policy(p, d)


def test_trusted_policy_outside_dir_rejected():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        p = os.path.join(d2, "evil.yaml")
        open(p, "w").close()
        assert not is_trusted_policy(p, d1)


def test_trusted_policy_traversal_rejected():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "../../../etc/passwd")
        assert not is_trusted_policy(p, d)
