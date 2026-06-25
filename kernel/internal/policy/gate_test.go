package policy

import (
	"testing"

	"agentos/kernel/internal/resource"
)

func samplePolicy() *Policy {
	return &Policy{
		Permissions: []Rule{
			{ResourceType: "path", Pattern: "examples/workspace/**", Actions: []string{"fs_read", "fs_list"}},
			{ResourceType: "path", Pattern: "examples/workspace/out/**", Actions: []string{"fs_write"}},
		},
	}
}

func TestGateAllowsReadInRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if !g.Allowed("fs_read", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Error("expected fs_read allowed")
	}
}

func TestGateDeniesReadOutsideRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "/etc/passwd"}) {
		t.Error("expected /etc/passwd denied")
	}
}

func TestGateDeniesTraversalEscape(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "examples/workspace/../../../etc/passwd"}) {
		t.Error("expected traversal denied")
	}
}

func TestGateEnforcesWriteRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Error("write outside out/ must be denied")
	}
	if !g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/out/result.txt"}) {
		t.Error("write inside out/ must be allowed")
	}
}

func TestGateDeniesUnknownResourceType(t *testing.T) {
	g := NewGate(samplePolicy())
	// 没有任何 db_table 规则，db_query 必须被拒
	if g.Allowed("db_query", resource.Resource{Type: "db_table", ID: "orders"}) {
		t.Error("unknown resource type must be denied")
	}
}

func TestGateDeniesUnknownAction(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("shell_exec", resource.Resource{Type: "path", ID: "examples/workspace/x"}) {
		t.Error("unknown action must be denied")
	}
}
