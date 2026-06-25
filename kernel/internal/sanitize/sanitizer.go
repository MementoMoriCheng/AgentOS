package sanitize

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

// FieldRule 是单字段的脱敏规则。
type FieldRule struct {
	Name       string `yaml:"name"`
	Strategy   string `yaml:"strategy"` // mask | hash | redact
	KeepPrefix int    `yaml:"keep_prefix"`
	KeepSuffix int    `yaml:"keep_suffix"`
}

type rulesFile struct {
	Fields []FieldRule `yaml:"fields"`
}

// omit 是 redact 的哨兵值，Sanitize 检测到它就跳过该字段（完全移除）。
type omit struct{}

var omitSentinel = omit{}

// Sanitizer 按字段名应用脱敏规则。规则只读，并发安全。
type Sanitizer struct {
	rules map[string]FieldRule
}

func NewFromRules(rules []FieldRule) *Sanitizer {
	m := make(map[string]FieldRule, len(rules))
	for _, r := range rules {
		m[r.Name] = r
	}
	return &Sanitizer{rules: m}
}

func LoadFromFile(path string) (*Sanitizer, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var rf rulesFile
	if err := yaml.Unmarshal(data, &rf); err != nil {
		return nil, err
	}
	return NewFromRules(rf.Fields), nil
}

// FieldSanitization 是脱敏摘要的一条：字段名 + 策略，不含原始值。
type FieldSanitization struct {
	Field    string
	Strategy string // mask | hash | redact
}

// Result 是 Sanitize 的产出：脱敏后数据 + 摘要（不含原始值）。
type Result struct {
	Data    map[string]any
	Summary []FieldSanitization
}

// Sanitize 对 data 中匹配规则的字段应用脱敏，返回新 data 与摘要（不改原 map）。
// redact 字段会被完全移除，但仍记入摘要。
func (s *Sanitizer) Sanitize(data map[string]any) Result {
	out := make(map[string]any, len(data))
	var summary []FieldSanitization
	for k, v := range data {
		rule, ok := s.rules[k]
		if !ok {
			out[k] = v
			continue
		}
		applied := s.apply(rule, v)
		summary = append(summary, FieldSanitization{Field: k, Strategy: rule.Strategy})
		if _, isOmit := applied.(omit); isOmit {
			continue // redact：完全移除字段（摘要已记）
		}
		out[k] = applied
	}
	return Result{Data: out, Summary: summary}
}

// SanitizeData 是便捷包装，仅返回 data（供不需要摘要的旧调用点用）。
func (s *Sanitizer) SanitizeData(data map[string]any) map[string]any {
	return s.Sanitize(data).Data
}

func (s *Sanitizer) apply(rule FieldRule, v any) any {
	str, ok := v.(string)
	if !ok {
		// 非字符串字段：hash 策略转字符串后哈希；其它策略原样返回。
		if rule.Strategy == "hash" {
			return hashValue(v)
		}
		return v
	}
	switch rule.Strategy {
	case "mask":
		return maskString(str, rule.KeepPrefix, rule.KeepSuffix)
	case "hash":
		return hashString(str)
	case "redact":
		return omitSentinel
	default:
		return str
	}
}

func maskString(s string, keepPrefix, keepSuffix int) string {
	if keepPrefix == 0 && keepSuffix == 0 {
		return "***"
	}
	if len(s) <= keepPrefix+keepSuffix {
		return "***"
	}
	return s[:keepPrefix] + strings.Repeat("*", len(s)-keepPrefix-keepSuffix) + s[len(s)-keepSuffix:]
}

func hashString(s string) string {
	h := sha256.Sum256([]byte(s))
	return "h_" + hex.EncodeToString(h[:])[:16]
}

func hashValue(v any) string {
	return hashString(fmt.Sprintf("%v", v))
}
