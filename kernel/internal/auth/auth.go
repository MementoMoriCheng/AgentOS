package auth

import "context"

// Identity 是调用方身份。
type Identity struct {
	Tenant string // MVP 单租户 = "default"
	User   string // MVP = "local"
}

// Authenticator 验证调用方身份。MVP 用 LocalAuthenticator（不验证，返回固定身份）。
// 未来加 mTLS/API key 是新实现，不改接口。
type Authenticator interface {
	Authenticate(ctx context.Context) (Identity, error)
}

// LocalAuthenticator 是 MVP 实现：不验证，返回固定 "local" 身份。
// 前提假设：本机只有可信进程能连 socket（由 socket 权限 0600 保证）。
type LocalAuthenticator struct{}

func (LocalAuthenticator) Authenticate(ctx context.Context) (Identity, error) {
	return Identity{Tenant: "default", User: "local"}, nil
}
