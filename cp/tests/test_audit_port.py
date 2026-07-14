import os
import tempfile

from cp.audit.audit_port import LedgerAuditPort
from cp.audit.ledger import Ledger, verify_chain


async def test_record_appends_to_ledger():
    with tempfile.TemporaryDirectory() as d:
        ledger = Ledger(os.path.join(d, "a.log"))
        port = LedgerAuditPort(ledger)
        await port.record({"session_id": "s1", "tool": "read",
                           "params": {"path": "x"}, "result": {"content": "y"},
                           "type": "primitive.called"})
        entries = await ledger.read_all()
        assert len(entries) == 1
        assert entries[0].tool == "read"
        assert entries[0].outcome == "called"


async def test_hash_chain_intact_after_multiple_records():
    with tempfile.TemporaryDirectory() as d:
        ledger = Ledger(os.path.join(d, "a.log"))
        port = LedgerAuditPort(ledger)
        for i in range(5):
            await port.record({"session_id": "s1", "tool": f"t{i}"})
        entries = await ledger.read_all()
        assert len(entries) == 5
        assert verify_chain(entries) is None  # 链完好


async def test_record_satisfies_audit_port_protocol():
    """LedgerAuditPort 实例 isinstance AuditPort(运行时校验)。"""
    from cp.ports import AuditPort
    with tempfile.TemporaryDirectory() as d:
        port = LedgerAuditPort(Ledger(os.path.join(d, "a.log")))
        assert isinstance(port, AuditPort)
