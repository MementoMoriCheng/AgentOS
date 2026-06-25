package policy

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadPolicy(t *testing.T) {
	p, err := LoadFromFile("../../../examples/policies/data_analyst.yaml")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if p.AgentRole != "data_analyst" {
		t.Errorf("role = %q, want data_analyst", p.AgentRole)
	}
	if len(p.Permissions) == 0 {
		t.Fatal("permissions empty")
	}
	if p.Permissions[0].ResourceType != "path" {
		t.Errorf("first rule resource_type = %q, want path", p.Permissions[0].ResourceType)
	}
	if p.MaxSteps != 20 {
		t.Errorf("max_steps = %d, want 20", p.MaxSteps)
	}
	if p.SanitizationPath == "" {
		t.Error("sanitization_path empty")
	}
	if p.MaxTokens != 50000 {
		t.Errorf("max_tokens = %d, want 50000", p.MaxTokens)
	}
}

func TestLoadPolicyDefaultMaxSteps(t *testing.T) {
	// 没有显式 max_steps 时应默认 20。用一个临时文件验证。
	dir := t.TempDir()
	path := filepath.Join(dir, "nopolicy.yaml")
	_ = os.WriteFile(path, []byte("agent_role: x\npermissions: []\n"), 0644)
	p, err := LoadFromFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if p.MaxSteps != 20 {
		t.Errorf("default max_steps = %d, want 20", p.MaxSteps)
	}
}
