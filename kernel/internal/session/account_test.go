package session

import "testing"

func TestAccountCharge(t *testing.T) {
	a := NewAccount(ResourceQuota{MaxSteps: 3, MaxTokens: 100})
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 1: %v", err)
	}
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 2: %v", err)
	}
	// 第三次步数到 3，未超（3 > 3 false）
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 3 should be ok: %v", err)
	}
	// 第四次步数到 4 > 3，超限
	if err := a.Charge(Usage{Steps: 1, Tokens: 10}); err == nil {
		t.Error("expected quota exceeded for steps")
	}
}

func TestAccountTokenExceeded(t *testing.T) {
	a := NewAccount(ResourceQuota{MaxSteps: 100, MaxTokens: 50})
	if err := a.Charge(Usage{Tokens: 30}); err != nil {
		t.Fatal(err)
	}
	if err := a.Charge(Usage{Tokens: 30}); err == nil {
		t.Error("expected token exceeded")
	}
}

func TestAccountZeroQuotaMeansUnlimited(t *testing.T) {
	// quota 为 0 表示不限制该项
	a := NewAccount(ResourceQuota{MaxSteps: 0, MaxTokens: 0})
	for i := 0; i < 100; i++ {
		if err := a.Charge(Usage{Steps: 1, Tokens: 1000}); err != nil {
			t.Fatalf("charge %d: %v (zero quota should be unlimited)", i, err)
		}
	}
}

func TestAccountUsedReflectsCharges(t *testing.T) {
	a := NewAccount(ResourceQuota{MaxSteps: 10, MaxTokens: 1000})
	a.Charge(Usage{Steps: 2, Tokens: 50})
	a.Charge(Usage{Steps: 3, Tokens: 100})
	used := a.Used()
	if used.Steps != 5 || used.Tokens != 150 {
		t.Errorf("used = %+v, want steps=5 tokens=150", used)
	}
}
