package auth

import (
	"context"
	"path/filepath"
	"testing"
)

func TestLocalAuthenticatorReturnsLocalIdentity(t *testing.T) {
	a := LocalAuthenticator{}
	id, err := a.Authenticate(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if id.User != "local" || id.Tenant != "default" {
		t.Errorf("got %+v", id)
	}
}

func TestIsTrustedPolicyInsideDir(t *testing.T) {
	dir := t.TempDir()
	policy := filepath.Join(dir, "data.yaml")
	if !IsTrustedPolicy(policy, dir) {
		t.Error("policy inside trusted dir should be trusted")
	}
}

func TestIsTrustedPolicyOutsideDir(t *testing.T) {
	dir := t.TempDir()
	other := t.TempDir()
	policy := filepath.Join(other, "evil.yaml")
	if IsTrustedPolicy(policy, dir) {
		t.Error("policy outside trusted dir should be rejected")
	}
}

func TestIsTrustedPolicyTraversalEscape(t *testing.T) {
	dir := t.TempDir()
	// 用 .. 试图逃出受信目录
	policy := filepath.Join(dir, "..", "..", "etc", "evil.yaml")
	if IsTrustedPolicy(policy, dir) {
		t.Error("traversal escape should be rejected")
	}
}

func TestIsTrustedPolicyNestedInside(t *testing.T) {
	dir := t.TempDir()
	policy := filepath.Join(dir, "sub", "deep", "policy.yaml")
	if !IsTrustedPolicy(policy, dir) {
		t.Error("nested policy inside trusted dir should be trusted")
	}
}
