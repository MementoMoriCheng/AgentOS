import os
from pathlib import PurePath


class PathTraversalError(ValueError):
    """请求路径清洗后含 ".." 段。"""


class SymlinkEscapeError(ValueError):
    """真实落点逃出所在树(符号链接逃逸)。"""


def resolve(requested: str) -> str:
    """把请求路径转成安全的绝对路径。

    拒绝:原始请求中任何 ".." 段;真实落点逃出所在树的符号链接。
    Python 的 os.path.realpath 对不存在路径会解析已存在前缀,
    等价于 Go 版的 resolveViaExistingAncestor,无需单独兜底。

    注:此处比 Go 版更严格 —— Go 在 filepath.Clean 之后才扫描 "..",
    而 Clean 会把 "a/../../x" 折叠成 "x" 导致漏检。本实现扫描原始请求,
    任何 ".." 段一律拒绝。
    """
    clean = os.path.normpath(requested)
    abs_path = os.path.abspath(clean)
    # 任何 ".." 段 = 穿越,直接拒。必须扫描原始 requested:normpath/Clean
    # 会折叠掉 "a/../../../x" 这类段,清洗后再扫会漏检。
    if ".." in PurePath(requested).parts:
        raise PathTraversalError(f"path traversal rejected: {requested}")
    real = os.path.realpath(abs_path)
    if real != abs_path and not _is_under(real, os.path.dirname(abs_path)):
        raise SymlinkEscapeError(f"symlink escape rejected: {requested} -> {real}")
    return real


def _is_under(path: str, root: str) -> bool:
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return False
    if rel == ".":
        return True
    return ".." not in PurePath(rel).parts
