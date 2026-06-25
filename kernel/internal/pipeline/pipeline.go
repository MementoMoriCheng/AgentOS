package pipeline

import (
	"context"

	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

// Response 是 Pipeline 一次调用的结果。
type Response struct {
	Allowed bool
	Errored bool
	Message string
	Result  map[string]any
}

// Pipeline 是 6 步统一管道。Kernel 核心只调它，不认识任何具体工具。
type Pipeline struct {
	registry *tools.Registry
	bus      eventbus.Bus
}

func New(registry *tools.Registry, bus eventbus.Bus) *Pipeline {
	return &Pipeline{registry: registry, bus: bus}
}

// Call 执行一次工具调用，经过：查找 → 提取权限 → 权限检查 → 资源扣减 → 执行 → 脱敏 → 审计（事件）。
func (p *Pipeline) Call(sess *session.Session, toolName string, params map[string]any) Response {
	ctx := context.Background()

	// 步骤 1：查找工具。未知工具 = 拒绝（不泄露工具清单细节）。
	tool, ok := p.registry.Get(toolName)
	if !ok {
		p.bus.Publish(eventbus.Event{
			Type: "tool.denied", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Allowed: false, Message: "permission denied"}
	}

	// 步骤 2：提取权限资源（工具自描述）。
	res := tool.PermissionKey(params)

	// 步骤 3：权限检查。不通过 → 拒绝 + 审计（拒绝原因不回传给调用方，防泄露）。
	if !sess.Gate.Allowed(toolName, res) {
		p.bus.Publish(eventbus.Event{
			Type: "tool.denied", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Allowed: false, Message: "permission denied"}
	}

	// 步骤 3.5：资源扣减。超限 → 硬终止 + quota.exceeded 事件。
	if err := sess.Account.Charge(session.Usage{Steps: 1}); err != nil {
		p.bus.Publish(eventbus.Event{
			Type: "quota.exceeded", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Errored: true, Message: "quota exceeded"}
	}

	// 步骤 4：执行工具。
	result, err := tool.Execute(ctx, params)
	if err != nil {
		p.bus.Publish(eventbus.Event{
			Type: "tool.errored", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Errored: true, Message: "tool error"}
	}

	// 步骤 5：脱敏（第一道安全防线，独立于工具）。保留摘要进事件。
	var sanSummary []eventbus.FieldSanitization
	if sess.Sanitizer != nil {
		sr := sess.Sanitizer.Sanitize(result.Data)
		result.Data = sr.Data
		// 摘要类型转换：sanitize.FieldSanitization → eventbus.FieldSanitization（解耦）。
		for _, f := range sr.Summary {
			sanSummary = append(sanSummary, eventbus.FieldSanitization{Field: f.Field, Strategy: f.Strategy})
		}
	}

	// 步骤 6：审计（通过事件触发 AuditSubscriber，不散落）。含脱敏摘要。
	p.bus.Publish(eventbus.Event{
		Type:     "tool.called", SessionID: sess.ID, Tool: toolName,
		Params: params, Result: result.Data, Sanitize: sanSummary,
	})

	return Response{Allowed: true, Result: result.Data}
}
