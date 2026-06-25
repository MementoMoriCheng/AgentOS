package sandbox

import (
	"fmt"
	"os"
	"path/filepath"
)

// Resolve 把请求路径转成安全的绝对路径。
// 拒绝：清洗后任何 ".." 段；真实落点逃出所在树的符号链接。
func Resolve(requested string) (string, error) {
	clean := filepath.Clean(requested)
	abs, err := filepath.Abs(clean)
	if err != nil {
		return "", err
	}
	for _, seg := range splitSegments(clean) {
		if seg == ".." {
			return "", fmt.Errorf("path traversal rejected: %s", requested)
		}
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		if os.IsNotExist(err) {
			// 目标文件还不存在（如 fs_write）。往上找存在的祖先，解析它，
			// 再把不存在的相对部分 join 回来。
			return resolveViaExistingAncestor(abs)
		}
		return "", err
	}
	if !isUnder(real, filepath.Dir(abs)) && real != abs {
		return "", fmt.Errorf("symlink escape rejected: %s -> %s", requested, real)
	}
	return real, nil
}

// resolveViaExistingAncestor 在目标不存在时，往上找到第一个存在的祖先目录，
// 对它做 EvalSymlinks（防符号链接逃逸），再把剩余路径接回去。
func resolveViaExistingAncestor(abs string) (string, error) {
	// 找出最长的存在的前缀目录。
	existing := filepath.Dir(abs)
	missing := filepath.Base(abs)
	for {
		_, statErr := os.Stat(existing)
		if statErr == nil {
			break
		}
		if !os.IsNotExist(statErr) {
			return "", statErr
		}
		// existing 也不存在，继续往上
		missing = filepath.Join(filepath.Base(existing), missing)
		parent := filepath.Dir(existing)
		if parent == existing {
			// 已到根（如 C:\），仍不存在——异常情况
			return "", fmt.Errorf("cannot find any existing ancestor for: %s", abs)
		}
		existing = parent
	}
	realAncestor, err := filepath.EvalSymlinks(existing)
	if err != nil {
		return "", fmt.Errorf("cannot resolve ancestor %s: %w", existing, err)
	}
	return filepath.Join(realAncestor, missing), nil
}

func splitSegments(p string) []string {
	var out []string
	for {
		base := filepath.Base(p)
		parent := filepath.Dir(p)
		if base == "" || base == "." || base == string(filepath.Separator) {
			break
		}
		// 加进结果（前置）
		out = append([]string{base}, out...)
		// 终止条件：parent 不再缩短（已到根，如 Windows 的 C:\）
		if parent == p || len(parent) >= len(p) {
			break
		}
		p = parent
	}
	return out
}

func isUnder(path, root string) bool {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return false
	}
	if rel == "." {
		return true
	}
	for _, seg := range splitSegments(rel) {
		if seg == ".." {
			return false
		}
	}
	return true
}
