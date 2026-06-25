package tools

import (
	"context"
	"encoding/json"

	"agentos/kernel/internal/resource"
)

// Result 是工具产出。
type Result struct {
	Data map[string]any
}

// Tool 是自描述的工具。Kernel 不认识任何具体工具，只调这个接口。
// 加新工具 = 实现这个接口 + 注册，Kernel 核心零改（开闭原则）。
type Tool interface {
	Name() string
	Schema() json.RawMessage                              // 给 LLM 的 function schema
	PermissionKey(params map[string]any) resource.Resource // 从参数提取权限资源
	Execute(ctx context.Context, params map[string]any) (Result, error)
}

// Registry 是工具注册表。
type Registry struct {
	tools map[string]Tool
}

func NewRegistry() *Registry {
	return &Registry{tools: map[string]Tool{}}
}

func (r *Registry) Register(t Tool) {
	r.tools[t.Name()] = t
}

func (r *Registry) Get(name string) (Tool, bool) {
	t, ok := r.tools[name]
	return t, ok
}
