import os
import tempfile

import pytest

from cp.sandbox.fs import resolve, PathTraversalError, SymlinkEscapeError


def test_resolve_normal_relative_path():
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            os.makedirs("examples/workspace/out", exist_ok=True)
            safe = resolve("examples/workspace/out/total.txt")
            # realpath 用系统原生分隔符(Windows 为 \),统一成正斜杠再比后缀
            assert safe.replace("\\", "/").endswith("examples/workspace/out/total.txt")
        finally:
            # 退出临时目录,避免 Windows 下 rmtree 因 cwd 被占用而 WinError 32
            os.chdir(orig)


def test_resolve_rejects_traversal():
    with pytest.raises(PathTraversalError):
        resolve("examples/workspace/../../../../etc/passwd")


def test_resolve_rejects_double_dot_segment():
    with pytest.raises(PathTraversalError):
        resolve("examples/workspace/out/../../../secret")


def test_resolve_rejects_absolute_unix_path():
    # 绝对路径不归 sandbox.Resolve 管(由 Gate glob 拒),但含 .. 仍要拒
    with pytest.raises(PathTraversalError):
        resolve("/etc/../etc/shadow")


def test_resolve_rejects_symlink_escape():
    """符号链接逃逸:workspace 内的 symlink 指向外部,resolve 必须拒。"""
    orig = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            os.makedirs("workspace/real", exist_ok=True)
            target = os.path.join(d, "outside_secret")
            open(target, "w").close()
            try:
                os.symlink(target, "workspace/escape_link")
            except OSError:
                pytest.skip("symlink not supported on this platform/privilege")
            with pytest.raises(SymlinkEscapeError):
                resolve("workspace/escape_link")
        finally:
            os.chdir(orig)
