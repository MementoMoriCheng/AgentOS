import os
import tempfile

import pytest

from cp.tools.tool import Registry
from cp.tools.fs_tools import FSReadTool, FSWriteTool, FSListTool
from cp.resource import Resource


def test_registry_register_and_get():
    reg = Registry()
    reg.register(FSReadTool())
    t, ok = reg.get("fs_read")
    assert ok and t.name() == "fs_read"
    _, ok = reg.get("nope")
    assert not ok


def test_fs_read_permission_key():
    assert FSReadTool().permission_key({"path": "a/b"}) == Resource("path", "a/b")


def test_fs_write_writes_and_reads_back():
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            reg = Registry()
            reg.register(FSWriteTool())
            reg.register(FSReadTool())
            w, _ = reg.get("fs_write")
            r, _ = reg.get("fs_read")
            w.execute({}, {"path": "examples/workspace/out/t.txt", "content": "hi"})
            res = r.execute({}, {"path": "examples/workspace/out/t.txt"})
            assert res.data["content"] == "hi"
        finally:
            # 退出临时目录,避免 Windows 下 rmtree 因 cwd 被占用而 WinError 32
            os.chdir(orig)


def test_fs_list_lists_entries():
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            os.makedirs("wd", exist_ok=True)
            open("wd/a.txt", "w").close()
            open("wd/b.txt", "w").close()
            res = FSListTool().execute({}, {"path": "wd"})
            assert set(res.data["entries"]) == {"a.txt", "b.txt"}
        finally:
            os.chdir(orig)


def test_fs_write_rejects_traversal():
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            with pytest.raises(Exception):
                FSWriteTool().execute({}, {"path": "../evil.txt", "content": "x"})
        finally:
            os.chdir(orig)
