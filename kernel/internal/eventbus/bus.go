package eventbus

import (
	"sync"
	"time"
)

// FieldSanitization 是脱敏摘要的一条：字段名 + 策略，不含原始值。
// 在 eventbus 内独立定义（不引入 sanitize 包），避免循环依赖。
type FieldSanitization struct {
	Field    string
	Strategy string // mask | hash | redact
}

// Event 是 Kernel 内一切值得关注的事件。
type Event struct {
	Type      string // tool.called | tool.denied | tool.errored | session.started | session.ended | quota.exceeded | run.* | runtime.*
	SessionID string
	RunID     string // Runtime 族事件才有
	Tool      string
	Params    map[string]any
	Result    map[string]any
	Identity  string                   // 启动 agent 的身份（来自 Authenticator）
	Sanitize  []FieldSanitization      // 脱敏摘要，仅 tool.called 有；不含原始值
	Payload   map[string]any           // Runtime 族事件的自由负载
	Timestamp int64
}

// Bus 是事件总线接口。
type Bus interface {
	Publish(event Event)
	// Subscribe 注册一个订阅者，返回取消订阅的函数。
	Subscribe(handler func(Event)) func()
}

// InProcess 同步分发事件给所有订阅者。
// 订阅者 panic 不影响主流程（recover）。
type InProcess struct {
	mu       sync.Mutex
	handlers []func(Event)
}

func NewInProcess() *InProcess {
	return &InProcess{}
}

func (b *InProcess) Subscribe(h func(Event)) func() {
	b.mu.Lock()
	id := len(b.handlers)
	b.handlers = append(b.handlers, h)
	b.mu.Unlock()
	return func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		if id < len(b.handlers) {
			b.handlers[id] = nil // 置空；Publish 跳过 nil
		}
	}
}

func (b *InProcess) Publish(e Event) {
	e.Timestamp = time.Now().UnixNano()
	b.mu.Lock()
	// 快照 handlers，避免回调里改订阅列表导致的竞态。
	handlers := append([]func(Event){}, b.handlers...)
	b.mu.Unlock()
	for _, h := range handlers {
		if h == nil {
			continue // 已取消订阅
		}
		func() {
			defer func() { _ = recover() }()
			h(e)
		}()
	}
}
