package session

import (
	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/sanitize"
)

// Session 是一个运行中 agent 的内核侧状态。
// 注意：Pipeline 不放在这里（避免 session ↔ pipeline 循环依赖）。
// Pipeline 由 Server 持有，通过 sessionID 关联。
type Session struct {
	ID        string
	Identity  string // 启动者身份
	Policy    *policy.Policy
	Gate      *policy.Gate
	Sanitizer *sanitize.Sanitizer
	Account   *Account
	Ledger    *audit.Ledger
}

// Snapshot 返回可持久化的会话状态。MVP 不调用，接口为未来持久化预留。
func (s *Session) Snapshot() ([]byte, error) {
	return []byte(s.ID), nil
}
