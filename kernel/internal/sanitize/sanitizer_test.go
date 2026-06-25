package sanitize

import (
	"fmt"
	"strings"
	"testing"
)

func TestMaskFull(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "id_card", Strategy: "mask"}})
	out := r.SanitizeData(map[string]any{"id_card": "110101199001011234"})
	if out["id_card"] != "***" {
		t.Errorf("got %v", out["id_card"])
	}
}

func TestMaskKeepPrefixSuffix(t *testing.T) {
	r := NewFromRules([]FieldRule{
		{Name: "phone", Strategy: "mask", KeepPrefix: 3, KeepSuffix: 4},
	})
	out := r.SanitizeData(map[string]any{"phone": "13812341234"})
	if out["phone"] != "138****1234" {
		t.Errorf("got %v", out["phone"])
	}
}

func TestHashStable(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "customer_id", Strategy: "hash"}})
	out1 := r.SanitizeData(map[string]any{"customer_id": "C001"})
	out2 := r.SanitizeData(map[string]any{"customer_id": "C001"})
	if out1["customer_id"] != out2["customer_id"] {
		t.Error("hash must be stable")
	}
	if out1["customer_id"] == "C001" {
		t.Error("hash must not be original")
	}
}

func TestRedact(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "remark", Strategy: "redact"}})
	out := r.SanitizeData(map[string]any{"remark": "secret info"})
	if _, ok := out["remark"]; ok {
		t.Error("redact must remove field")
	}
}

func TestUnmatchedFieldUntouched(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "phone", Strategy: "mask"}})
	out := r.SanitizeData(map[string]any{"amount": 100})
	if out["amount"] != 100 {
		t.Errorf("amount should be untouched, got %v", out["amount"])
	}
}

func TestLoadFromFile(t *testing.T) {
	r, err := LoadFromFile("../../../examples/sanitization/pii_rules.yaml")
	if err != nil {
		t.Fatal(err)
	}
	out := r.SanitizeData(map[string]any{"id_card": "x", "customer_id": "y"})
	if out["id_card"] != "***" {
		t.Errorf("id_card not masked: %v", out["id_card"])
	}
	if out["customer_id"] == "y" {
		t.Error("customer_id not hashed")
	}
}

func TestMaskShortString(t *testing.T) {
	// 字符串比 keep_prefix+keep_suffix 还短时，应整体掩码
	r := NewFromRules([]FieldRule{{Name: "phone", Strategy: "mask", KeepPrefix: 3, KeepSuffix: 4}})
	out := r.SanitizeData(map[string]any{"phone": "12345"})
	if out["phone"] != "***" {
		t.Errorf("short string should be fully masked, got %v", out["phone"])
	}
}

func TestSanitizeReturnsSummary(t *testing.T) {
	s := NewFromRules([]FieldRule{
		{Name: "phone", Strategy: "mask", KeepPrefix: 3, KeepSuffix: 4},
		{Name: "customer_id", Strategy: "hash"},
		{Name: "remark", Strategy: "redact"},
	})

	res := s.Sanitize(map[string]any{
		"phone":       "13800001234",
		"customer_id": "C-100",
		"remark":      "very secret",
		"safe":        "keep me",
	})

	// 摘要应记录被处理的 3 个字段。
	wantFields := map[string]string{
		"phone":       "mask",
		"customer_id": "hash",
		"remark":      "redact",
	}
	got := map[string]string{}
	for _, f := range res.Summary {
		got[f.Field] = f.Strategy
	}
	if len(got) != len(wantFields) {
		t.Fatalf("summary len = %d, want %d (%v)", len(got), len(wantFields), got)
	}
	for k, v := range wantFields {
		if got[k] != v {
			t.Errorf("summary[%s] = %q, want %q", k, got[k], v)
		}
	}

	// 摘要里绝不能含原始值。
	dump := fmt.Sprintf("%v", res.Summary)
	for _, secret := range []string{"13800001234", "C-100", "very secret"} {
		if strings.Contains(dump, secret) {
			t.Errorf("summary leaks original value %q: %v", secret, res.Summary)
		}
	}
	// redact 字段在 data 里被移除。
	if _, ok := res.Data["remark"]; ok {
		t.Error("redact field should be removed from data")
	}
}
