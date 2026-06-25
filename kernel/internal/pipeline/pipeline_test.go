package pipeline

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sanitize"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

// fakeTool 是一个可控的测试工具，模拟真实工具但不碰文件系统。
type fakeTool struct {
	name   string
	result map[string]any
}

func (f fakeTool) Name() string                                 { return f.name }
func (f fakeTool) Schema() json.RawMessage                       { return nil }
func (f fakeTool) PermissionKey(params map[string]any) resource.Resource {
	return resource.Resource{Type: "path", ID: params["path"].(string)}
}
func (f fakeTool) Execute(ctx context.Context, params map[string]any) (tools.Result, error) {
	return tools.Result{Data: f.result}, nil
}

func newTestSession(t *testing.T, maxSteps int) *session.Session {
	p := &policy.Policy{
		Permissions: []policy.Rule{
			{ResourceType: "path", Pattern: "ws/**", Actions: []string{"fake"}},
		},
		MaxSteps:  maxSteps,
		MaxTokens: 100000,
	}
	return &session.Session{
		ID:        "s1",
		Policy:    p,
		Gate:      policy.NewGate(p),
		Sanitizer: sanitize.NewFromRules([]sanitize.FieldRule{{Name: "secret", Strategy: "mask"}}),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: maxSteps, MaxTokens: 100000}),
	}
}

func TestPipelineAllowedPath(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{"content": "data", "secret": "pii"}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 20)
	resp := pipe.Call(sess, "fake", map[string]any{"path": "ws/x.csv"})
	if !resp.Allowed {
		t.Fatal("expected allowed")
	}
	// 脱敏应在结果中生效
	if resp.Result["secret"] == "pii" {
		t.Error("secret should be sanitized")
	}
	if resp.Result["secret"] != "***" {
		t.Errorf("secret should be masked to ***, got %v", resp.Result["secret"])
	}
}

func TestPipelineDeniedPath(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 20)
	resp := pipe.Call(sess, "fake", map[string]any{"path": "/etc/passwd"})
	if resp.Allowed {
		t.Error("expected denied")
	}
	if resp.Message == "" {
		t.Error("denied should have generic message")
	}
}

func TestPipelineUnknownTool(t *testing.T) {
	bus := eventbus.NewInProcess()
	pipe := New(tools.NewRegistry(), bus)
	sess := newTestSession(t, 20)
	resp := pipe.Call(sess, "nonexistent", map[string]any{"path": "ws/x"})
	if resp.Allowed {
		t.Error("unknown tool should be denied")
	}
}

func TestPipelinePublishesEvents(t *testing.T) {
	bus := eventbus.NewInProcess()
	var events []eventbus.Event
	bus.Subscribe(func(e eventbus.Event) { events = append(events, e) })

	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 20)
	pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})

	found := false
	for _, e := range events {
		if e.Type == "tool.called" {
			found = true
		}
	}
	if !found {
		t.Error("expected tool.called event")
	}
}

func TestPipelineDeniedPublishesDeniedEvent(t *testing.T) {
	bus := eventbus.NewInProcess()
	var gotType string
	bus.Subscribe(func(e eventbus.Event) { gotType = e.Type })

	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 20)
	pipe.Call(sess, "fake", map[string]any{"path": "/etc/passwd"})

	if gotType != "tool.denied" {
		t.Errorf("expected tool.denied event, got %s", gotType)
	}
}

func TestPipelineQuotaExceededTerminates(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 1) // MaxSteps=1
	// 第一次：Charge 后 used.Steps=1，未超（1>1 false），允许
	resp := pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})
	if !resp.Allowed {
		t.Fatal("first call should be allowed")
	}
	// 第二次：Charge 后 used.Steps=2 > 1，超限
	resp = pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})
	if resp.Allowed {
		t.Error("second call should be quota exceeded (denied form)")
	}
	if !resp.Errored {
		t.Error("quota exceeded should set Errored=true")
	}
	if resp.Message == "" {
		t.Error("quota exceeded should have message")
	}
}

func TestPipelineQuotaExceededPublishesEvent(t *testing.T) {
	bus := eventbus.NewInProcess()
	var lastType string
	bus.Subscribe(func(e eventbus.Event) { lastType = e.Type })

	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t, 1)
	pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})  // ok
	pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})  // 超限

	if lastType != "quota.exceeded" {
		t.Errorf("expected quota.exceeded event, got %s", lastType)
	}
}

// TestPipelineEmitsSanitizeSummary 验证 tool.called 事件含脱敏摘要，且不泄露原始值。
// 这是 spec §3.2 决策 A 的对抗断言。
func TestPipelineEmitsSanitizeSummary(t *testing.T) {
	bus := eventbus.NewInProcess()
	var events []eventbus.Event
	bus.Subscribe(func(e eventbus.Event) { events = append(events, e) })

	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{"content": "data", "secret": "topsecret-value"}})
	pipe := New(reg, bus)

	// sanitizer 配 secret → mask
	sess := &session.Session{
		ID:        "s1",
		Policy:    &policy.Policy{Permissions: []policy.Rule{{ResourceType: "path", Pattern: "ws/**", Actions: []string{"fake"}}}, MaxSteps: 20, MaxTokens: 100000},
		Gate:      policy.NewGate(&policy.Policy{Permissions: []policy.Rule{{ResourceType: "path", Pattern: "ws/**", Actions: []string{"fake"}}}}),
		Sanitizer: sanitize.NewFromRules([]sanitize.FieldRule{{Name: "secret", Strategy: "mask"}}),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: 20, MaxTokens: 100000}),
	}

	resp := pipe.Call(sess, "fake", map[string]any{"path": "ws/x.csv"})
	if !resp.Allowed {
		t.Fatal("expected allowed")
	}

	// 找到 tool.called 事件
	var called *eventbus.Event
	for i := range events {
		if events[i].Type == "tool.called" {
			called = &events[i]
			break
		}
	}
	if called == nil {
		t.Fatal("expected a tool.called event")
	}

	// 摘要应记录 secret 字段被 mask。
	if len(called.Sanitize) != 1 {
		t.Fatalf("expected 1 sanitize entry, got %d (%+v)", len(called.Sanitize), called.Sanitize)
	}
	if called.Sanitize[0].Field != "secret" || called.Sanitize[0].Strategy != "mask" {
		t.Errorf("unexpected sanitize summary: %+v", called.Sanitize)
	}

	// 对抗断言：原始敏感值绝不能出现在事件任何字段里。
	dump := fmt.Sprintf("%+v", called)
	if strings.Contains(dump, "topsecret-value") {
		t.Error("tool.called event leaks original sensitive value")
	}
}
