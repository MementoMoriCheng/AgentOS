package auth

import (
	"path/filepath"
	"strings"
)

// IsTrustedPolicy 检查 Policy 路径是否在某个受信目录内。
// 防止恶意进程加载全权限 Policy 绕过所有限制。
// trustedDir 是允许的根目录；policyPath 可以是相对或绝对路径。
func IsTrustedPolicy(policyPath, trustedDir string) bool {
	abs, err := filepath.Abs(policyPath)
	if err != nil {
		return false
	}
	trustedAbs, err := filepath.Abs(trustedDir)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(trustedAbs, abs)
	if err != nil {
		return false
	}
	// rel 不能以 ".." 开头（逃出受信目录）
	relSlash := filepath.ToSlash(rel)
	if relSlash == ".." || strings.HasPrefix(relSlash, "../") {
		return false
	}
	return true
}
