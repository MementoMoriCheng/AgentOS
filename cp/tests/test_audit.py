import json
import os
import tempfile

from cp.audit.ledger import Ledger, Entry, verify_chain
from cp.audit.subscriber import register_audit_subscriber
from cp.eventbus.bus import Event, InProcess


def _entry(tool="fs_read", outcome="allowed"):
    return Entry(session_id="s1", tool=tool, params_json="{}", outcome=outcome, result_json="{}")


async def test_append_and_read_back():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        await ledger.append(_entry())
        await ledger.append(_entry(tool="fs_write"))
        entries = await ledger.read_all()
        assert len(entries) == 2
        assert entries[0].tool == "fs_read"
        assert entries[1].tool == "fs_write"


async def test_chain_verifies_when_intact():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        await ledger.append(_entry())
        await ledger.append(_entry())
        assert verify_chain(await ledger.read_all()) is None


async def test_chain_detects_tamper():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        await ledger.append(_entry())
        await ledger.append(_entry())
        # 篡改第二条的 tool
        entries = await ledger.read_all()
        entries[1] = Entry(session_id="s1", tool="tampered",
                           params_json="{}", outcome="allowed", result_json="{}",
                           prev_hash=entries[1].prev_hash, hash=entries[1].hash)
        err = verify_chain(entries)
        assert err is not None


async def test_reload_picks_up_last_hash():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        await Ledger(path).append(_entry())
        # 新实例加载已有文件,继续追加,链仍连续
        ledger2 = Ledger(path)
        await ledger2.append(_entry())
        assert verify_chain(await ledger2.read_all()) is None


async def test_subscriber_writes_audit_for_relevant_events():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        ledger = Ledger(path)
        bus = InProcess()
        register_audit_subscriber(ledger, bus)
        await bus.publish(Event(type="tool.called", session_id="s1", tool="fs_read",
                                params={"path": "x"}, result={"content": "y"}))
        await bus.publish(Event(type="runtime.step", session_id="s1"))  # 不审计
        entries = await ledger.read_all()
        assert len(entries) == 1
        assert entries[0].tool == "fs_read"
        assert entries[0].outcome == "allowed"
