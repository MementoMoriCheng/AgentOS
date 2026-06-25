package sandbox

// Sandbox 是执行环境抽象。MVP 只有 InProcess（不跑任意代码）。
// 未来加 WasmSandbox / ContainerSandbox 支持代码执行。
type Sandbox interface {
	// Type 返回沙箱类型标识（"inprocess" | "wasm" | "container"）。
	Type() string
}
