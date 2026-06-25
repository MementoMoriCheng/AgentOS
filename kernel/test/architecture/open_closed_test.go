package architecture

import (
	"context"
	"encoding/json"
	"testing"

	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/pipeline"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sanitize"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

// DBQueryStub 是一个全新的、和 fs 完全无关的工具。
// 它证明：加新工具只需实现 Tool 接口，Kernel 核心（Pipeline/Gate）零改。
type DBQueryStub struct{}

func (DBQueryStub) Name() string { return "db_query" }

func (DBQueryStub) Schema() json.RawMessage {
	return json.RawMessage(`{"name":"db_query","description":"stub"}`)
}

func (DBQueryStub) PermissionKey(params map[string]any) resource.Resource {
	table, _ := params["table"].(string)
	return resource.Resource{Type: "db_table", ID: table}
}

func (DBQueryStub) Execute(ctx context.Context, params map[string]any) (tools.Result, error) {
	return tools.Result{Data: map[string]any{"rows": []map[string]any{{"id": 1}}}}, nil
}

// 静态断言：DBQueryStub 实现了 Tool 接口
var _ tools.Tool = DBQueryStub{}

func TestOpenClosedAddingNewToolRequiresZeroKernelChanges(t *testing.T) {
	// 用一个含 db_table 规则的策略（现有 Gate 无需改动即可匹配新资源类型）
	p := &policy.Policy{
		Permissions: []policy.Rule{
			{ResourceType: "db_table", Pattern: "sales.orders", Actions: []string{"db_query"}},
		},
		MaxSteps: 10, MaxTokens: 100000,
	}
	sess := &session.Session{
		ID:        "arch-test",
		Policy:    p,
		Gate:      policy.NewGate(p),
		Sanitizer: sanitize.NewFromRules(nil),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: 10, MaxTokens: 100000}),
	}

	reg := tools.NewRegistry()
	reg.Register(DBQueryStub{}) // 注册新工具——这是唯一新增的代码
	bus := eventbus.NewInProcess()
	pipe := pipeline.New(reg, bus)

	// 允许查询 sales.orders（Gate 用 db_table 规则匹配，无需认识 db_query 工具）
	resp := pipe.Call(sess, "db_query", map[string]any{"table": "sales.orders"})
	if !resp.Allowed {
		t.Fatal("db_query on sales.orders must be allowed by existing Gate")
	}
	// 结果应返回（脱敏层为空，原样）
	rows, _ := resp.Result["rows"].([]map[string]any)
	if len(rows) != 1 {
		t.Errorf("expected 1 row, got %v", resp.Result["rows"])
	}

	// 拒绝查询未授权的表（finance.salaries 不匹配 sales.orders 模式）
	resp = pipe.Call(sess, "db_query", map[string]any{"table": "finance.salaries"})
	if resp.Allowed {
		t.Fatal("db_query on finance.salaries must be denied")
	}
}

func TestOpenClosedNewToolPublishesEvents(t *testing.T) {
	p := &policy.Policy{
		Permissions: []policy.Rule{
			{ResourceType: "db_table", Pattern: "sales.orders", Actions: []string{"db_query"}},
		},
		MaxSteps: 10, MaxTokens: 100000,
	}
	sess := &session.Session{
		ID: "arch-test2", Policy: p, Gate: policy.NewGate(p),
		Sanitizer: sanitize.NewFromRules(nil),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: 10, MaxTokens: 100000}),
	}

	reg := tools.NewRegistry()
	reg.Register(DBQueryStub{})
	bus := eventbus.NewInProcess()
	pipe := pipeline.New(reg, bus)

	var sawEvent bool
	bus.Subscribe(func(e eventbus.Event) {
		if e.Type == "tool.called" && e.Tool == "db_query" {
			sawEvent = true
		}
	})
	pipe.Call(sess, "db_query", map[string]any{"table": "sales.orders"})
	if !sawEvent {
		t.Error("db_query should publish tool.called event through existing EventBus")
	}
}
