package session

import (
	"errors"
	"sync"
)

// ResourceQuota 是单个 agent 的资源预算。
type ResourceQuota struct {
	MaxSteps  int
	MaxTokens int
	// MaxDuration / MaxToolCalls 留后续
}

// Usage 是已消耗的资源。
type Usage struct {
	Steps  int
	Tokens int
}

// Account 累计资源消耗，超限拒绝。并发安全。
type Account struct {
	mu    sync.Mutex
	quota ResourceQuota
	used  Usage
}

func NewAccount(q ResourceQuota) *Account {
	return &Account{quota: q}
}

// Charge 扣减资源。任一项超限返回 ErrQuotaExceeded（但已累加，调用方应终止）。
func (a *Account) Charge(u Usage) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.used.Steps += u.Steps
	a.used.Tokens += u.Tokens
	if a.quota.MaxSteps > 0 && a.used.Steps > a.quota.MaxSteps {
		return ErrQuotaExceeded
	}
	if a.quota.MaxTokens > 0 && a.used.Tokens > a.quota.MaxTokens {
		return ErrQuotaExceeded
	}
	return nil
}

// Used 返回当前累计消耗（用于审计/展示）。
func (a *Account) Used() Usage {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.used
}

var ErrQuotaExceeded = errors.New("quota exceeded")
