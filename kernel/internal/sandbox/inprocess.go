package sandbox

// InProcess 是 MVP 唯一的 Sandbox 实现：工具在 Kernel 进程内执行，不跑任意代码。
// path 型工具的路径安全由 Resolve 保证。
type InProcess struct{}

func (InProcess) Type() string { return "inprocess" }
