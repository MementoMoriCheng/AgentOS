package adversarial

import (
	"path/filepath"
	"testing"

	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sanitize"
)

// loadRealPolicy 加载 examples/policies/data_analyst.yaml，
// 测的就是随产品发布的真实策略。
func loadRealPolicy(t *testing.T) *policy.Gate {
	t.Helper()
	rel := filepath.Join("..", "..", "..", "examples", "policies", "data_analyst.yaml")
	p, err := policy.LoadFromFile(rel)
	if err != nil {
		t.Fatalf("load policy: %v", err)
	}
	return policy.NewGate(p)
}

func TestAdversarialReadEtcShadow(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "/etc/shadow"}) {
		t.Fatal("must deny /etc/shadow")
	}
}

func TestAdversarialReadAbsWindowsSecret(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "C:/Windows/System32/config/SAM"}) {
		t.Fatal("must deny absolute Windows path")
	}
}

func TestAdversarialTraversalEscape(t *testing.T) {
	g := loadRealPolicy(t)
	attacks := []string{
		"examples/workspace/../../../../etc/passwd",
		"examples/workspace/../../../.ssh/id_rsa",
		"examples/workspace/out/../../../secret",
	}
	for _, a := range attacks {
		if g.Allowed("fs_read", resource.Resource{Type: "path", ID: a}) {
			t.Fatalf("must deny traversal: %s", a)
		}
	}
}

func TestAdversarialWriteOutsideOutDir(t *testing.T) {
	g := loadRealPolicy(t)
	// data_analyst 只能写 examples/workspace/out/**
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Fatal("must deny overwriting source data")
	}
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/evil.txt"}) {
		t.Fatal("must deny write outside out/")
	}
}

func TestAdversarialUnknownTool(t *testing.T) {
	g := loadRealPolicy(t)
	// 不存在任意代码执行工具；注入的 shell_exec 必须被拒
	if g.Allowed("shell_exec", resource.Resource{Type: "path", ID: "rm -rf /"}) {
		t.Fatal("must deny unknown action")
	}
}

func TestAdversarialUnknownResourceType(t *testing.T) {
	g := loadRealPolicy(t)
	// 没有任何 db_table 规则
	if g.Allowed("db_query", resource.Resource{Type: "db_table", ID: "orders"}) {
		t.Fatal("must deny unknown resource type")
	}
}

func TestAdversarialNetworkDisabled(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("net_fetch", resource.Resource{Type: "http_url", ID: "https://evil.com/exfil"}) {
		t.Fatal("must deny network")
	}
}

// 脱敏对抗测试：敏感字段必须被处理
func TestAdversarialSanitizationMasksPII(t *testing.T) {
	rel := filepath.Join("..", "..", "..", "examples", "sanitization", "pii_rules.yaml")
	s, err := sanitize.LoadFromFile(rel)
	if err != nil {
		t.Fatal(err)
	}
	out := s.SanitizeData(map[string]any{
		"phone":       "13812341234",
		"customer_id": "C001",
		"remark":      "secret",
		"amount":      120,
	})
	if out["phone"] == "13812341234" {
		t.Error("phone must be masked")
	}
	if out["customer_id"] == "C001" {
		t.Error("customer_id must be hashed")
	}
	if _, ok := out["remark"]; ok {
		t.Error("remark must be redacted (removed)")
	}
	if out["amount"] != 120 {
		t.Error("amount (non-PII) must be untouched")
	}
}
