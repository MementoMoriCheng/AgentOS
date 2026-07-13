import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

GENESIS_HASH = "0" * 64


@dataclass
class Entry:
    """一条被审计的事件记录。"""
    session_id: str = ""
    timestamp_nano: int = 0
    tool: str = ""
    params_json: str = ""
    outcome: str = ""  # allowed | denied | error | session_started | session_ended | quota_exceeded
    result_json: str = ""
    prev_hash: str = ""
    hash: str = ""


class Ledger:
    """append-only、hash 链的审计日志。"""

    def __init__(self, path: str):
        self._mu = threading.Lock()
        self.path = path
        self.last_hash = GENESIS_HASH
        # 若文件已存在,加载最后一条的 hash 作为链尾
        if os.path.exists(path):
            for e in self.read_all():
                self.last_hash = e.hash

    def append(self, e: Entry) -> None:
        with self._mu:
            e.timestamp_nano = time.time_ns()
            e.prev_hash = self.last_hash
            e.hash = _compute_hash(e.prev_hash, e)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(e)) + "\n")
            self.last_hash = e.hash

    def read_all(self) -> List[Entry]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(Entry(**json.loads(line)))
        return out


def verify_chain(entries: List[Entry]) -> Optional[str]:
    """重算所有 hash,任一环断裂返回错误描述;完好返回 None。"""
    prev = GENESIS_HASH
    for i, e in enumerate(entries):
        if e.prev_hash != prev:
            return f"chain broken at entry {i}: prev_hash mismatch"
        if _compute_hash(e.prev_hash, e) != e.hash:
            return f"chain broken at entry {i}: hash mismatch"
        prev = e.hash
    return None


def _compute_hash(prev: str, e: Entry) -> str:
    payload = f"{prev}|{e.session_id}|{e.timestamp_nano}|{e.tool}|{e.params_json}|{e.outcome}|{e.result_json}"
    return hashlib.sha256(payload.encode()).hexdigest()
