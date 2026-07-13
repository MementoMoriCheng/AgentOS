import os


def is_trusted_policy(policy_path: str, trusted_dir: str) -> bool:
    """检查 Policy 路径是否在某个受信目录内。防止加载全权限恶意 Policy。"""
    try:
        abs_p = os.path.abspath(policy_path)
        abs_dir = os.path.abspath(trusted_dir)
        rel = os.path.relpath(abs_p, abs_dir)
    except ValueError:
        return False
    # rel 不能以 ".." 开头(逃出受信目录)
    if rel == ".." or rel.startswith(".." + os.sep) or rel.startswith("../"):
        return False
    return True
