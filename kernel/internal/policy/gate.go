package policy

import (
	"path/filepath"
	"strings"

	"agentos/kernel/internal/resource"

	"github.com/bmatcuk/doublestar/v4"
)

// Gate 按 Policy 的规则匹配 (action, resource)。
// 它不认识任何工具名，只做通用的三元匹配。
type Gate struct {
	rules []Rule
}

func NewGate(p *Policy) *Gate {
	return &Gate{rules: p.Permissions}
}

// Allowed 报告 action 是否允许对 res 执行。
func (g *Gate) Allowed(action string, res resource.Resource) bool {
	for _, rule := range g.rules {
		if rule.ResourceType != res.Type {
			continue
		}
		if !containsAction(rule.Actions, action) {
			continue
		}
		if matchID(rule.Pattern, rule.ResourceType, res.ID) {
			return true
		}
	}
	return false
}

func containsAction(actions []string, action string) bool {
	for _, a := range actions {
		if a == action {
			return true
		}
	}
	return false
}

// matchID 按资源类型决定匹配方式。
// path 类型：glob 匹配 + 拒绝穿越/绝对路径。
// 其它类型：精确匹配 ID（未来可扩展）。
func matchID(pattern, resourceType, id string) bool {
	if resourceType == "path" {
		return matchPath(pattern, id)
	}
	return pattern == id
}

func matchPath(pattern, path string) bool {
	// 统一用正斜杠，避免 Windows 反斜杠与 glob pattern 不匹配。
	clean := filepath.ToSlash(filepath.Clean(path))
	pattern = filepath.ToSlash(filepath.Clean(pattern))
	if filepath.IsAbs(filepath.Clean(path)) {
		return false
	}
	for _, seg := range strings.Split(clean, "/") {
		if seg == ".." {
			return false
		}
	}
	ok, err := doublestar.Match(pattern, clean)
	return err == nil && ok
}
