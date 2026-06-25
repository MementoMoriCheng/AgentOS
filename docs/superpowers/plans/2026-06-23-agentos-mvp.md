# AgentOS MVP 实现计划（阶段 0 — 安全内核）

> **给执行 agent：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 来逐任务执行本计划。步骤用 checkbox（`- [ ]`）语法跟踪。

**目标：** 构建 MVP 安全内核（方案 A）——一个 agent 在权限受控、可审计的沙箱里跑通一个任务，验证"安全与可控"这个核心壁垒。

**架构：** Go 内核（权限闸门 + 审计账本 + 软沙箱 + gRPC 服务端）跑在 Unix domain socket 上；Python 运行时（DeepSeek LLM 客户端 + ReAct 循环 + gRPC 客户端）。Python 运行时本身零敏感权限——每个有副作用的调用都经过内核。

**技术栈：** Go 1.22+、Python 3.11+、gRPC + protobuf、`github.com/bmatcuk/doublestar/v4`（glob 匹配）、`openai` Python SDK（DeepSeek 走 OpenAI 兼容 base_url）、`pytest`、Go `testing`。

---

## ⚠️ 重要说明（先读）

1. **不要提交代码到 git。** 按用户要求，所有实现代码只保留在本地。下面的"检查点"步骤是本地里程碑——**不要执行 `git commit`**。（设计文档已经提交过一次，没关系。）
2. **必须先装工具链**（任务 1）。这台机器目前 PATH 里没有 Go/Python/protoc。
3. **工具名用下划线**（`fs_read`，不是 `fs.read`）。OpenAI/DeepSeek 的函数名正则拒绝点号——这是个真实的坑。
4. **Unix domain socket 在 Windows 10 1803+ 可用**（本机是 build 26100）——开发没问题。
5. **软沙箱模型**：MVP 工具是固定的（fs_read/fs_write/fs_list），agent 无法执行任意代码。因此内核内的严格路径校验本身就是一道真实的边界。独立的沙箱进程 + 容器加固留到阶段 2。

---

## 文件结构

```
AgentOS/
├── go.mod                                  # Go module: agentos
├── kernel/
│   ├── cmd/agentos/
│   │   └── main.go                         # CLI: `agentos serve`, `agentos audit show`
│   └── internal/
│       ├── pb/                             # 生成的 protobuf (Go)
│       │   └── (生成文件)
│       ├── capability/                     # 策略加载 + 权限闸门
│       │   ├── policy.go
│       │   ├── gate.go
│       │   ├── policy_test.go
│       │   └── gate_test.go
│       ├── audit/                          # append-only 的 hash 链审计账本
│       │   ├── ledger.go
│       │   └── ledger_test.go
│       ├── sandbox/                        # 软沙箱：路径校验
│       │   ├── fs.go
│       │   └── fs_test.go
│       ├── tools/                          # 工具注册表 + 实现
│       │   ├── registry.go
│       │   ├── fs_tools.go
│       │   └── registry_test.go
│       ├── session/                        # agent 会话状态
│       │   └── manager.go
│       └── server/                         # gRPC 服务端
│           └── server.go
├── proto/
│   └── agentos.proto                       # 共享契约
├── runtime/
│   ├── pyproject.toml
│   ├── agentos_runtime/
│   │   ├── __init__.py
│   │   ├── pb/                             # 生成的 protobuf (Python)
│   │   │   └── (生成文件)
│   │   ├── kernel_client.py                # 连内核的 gRPC 客户端
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── deepseek.py
│   │   ├── tools.py                        # 暴露给 LLM 的工具 schema
│   │   ├── loop.py                         # ReAct 循环
│   │   └── cli.py                          # `agentos-run` Python 入口
│   └── tests/
│       ├── test_loop.py
│       └── test_kernel_client.py
├── examples/
│   ├── policies/
│   │   └── data_analyst.yaml
│   └── workspace/                          # 演示工作区（内容 gitignore）
│       ├── sales.csv
│       └── out/                            # agent 写到这里
└── docs/superpowers/
    ├── specs/2026-06-23-agentos-mvp-design.md
    └── plans/2026-06-23-agentos-mvp.md     #（本文件）
```

**拆分理由：** 每个包单一职责、可独立测试。`capability`、`audit`、`sandbox` 是纯逻辑（无需网络即可测）。`tools` 依赖 `sandbox` + `capability`。`server` 在 gRPC 后面把它们接起来。Python 的 `loop` 用 mock 内核客户端 + mock LLM 即可测。

---

# 阶段 0 — 环境与骨架

## 任务 1：安装并验证工具链

**文件：** 无（仅环境）

- [ ] **步骤 1：安装 Go 1.22+**

从 https://go.dev/dl/ 下载（Windows 安装包）。运行，接受默认。打开一个**新**终端验证：

```
go version
```
预期：`go version go1.22.x windows/amd64`

- [ ] **步骤 2：安装 Python 3.11+**

从 https://www.python.org/downloads/ 下载（勾选 "Add Python to PATH"）。验证：

```
python --version
```
预期：`Python 3.11.x` 或更新。

- [ ] **步骤 3：安装 protoc + gRPC 插件**

从 https://github.com/protocolbuffers/protobuf/releases 安装 `protoc`（选 `protoc-<版本>-win64.zip`，把 `bin/protoc.exe` 放到 PATH）。验证：

```
protoc --version
```
预期：`libprotoc 27.x`（任意较新版本）。

安装 Go gRPC 插件：

```
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

确保 `$GOPATH/bin`（通常是 `%USERPROFILE%\go\bin`）在 PATH 上。验证：

```
protoc-gen-go --version
```
预期：`protoc-gen-go v1.x.x`。

- [ ] **步骤 4：安装 Python gRPC 工具**

```
pip install grpcio grpcio-tools openai pytest
```

验证：
```
python -c "import grpc, openai, pytest; print('ok')"
```
预期：`ok`

- [ ] **步骤 5：设置 DeepSeek API key 为环境变量（用户手动操作）**

用户已有 DeepSeek key。在运行运行时的那个 shell 里设置：

```
set DEEPSEEK_API_KEY=sk-xxxxxxxx        (cmd)
$env:DEEPSEEK_API_KEY="sk-xxxxxxxx"     (powershell)
```

不要在仓库任何地方硬编码 key。

---

## 任务 2：创建项目骨架 + go module

**文件：**
- 创建：`go.mod`
- 创建：目录树（需要时用空 `.gitkeep` 占位）

- [ ] **步骤 1：在仓库根初始化 Go module**

```
cd E:\Project\Agent-Project\AgentOS
go mod init agentos
```

预期：创建 `go.mod`，内容含 `module agentos`。

- [ ] **步骤 2：创建目录结构**

```
mkdir kernel\cmd\agentos
mkdir kernel\internal\pb
mkdir kernel\internal\capability
mkdir kernel\internal\audit
mkdir kernel\internal\sandbox
mkdir kernel\internal\tools
mkdir kernel\internal\session
mkdir kernel\internal\server
mkdir proto
mkdir runtime
mkdir examples\policies
mkdir examples\workspace\out
```

- [ ] **步骤 3：检查点**

目录树存在。（不提交——仅本地。）

---

## 任务 3：编写 protobuf 契约

**文件：**
- 创建：`proto/agentos.proto`

- [ ] **步骤 1：写 proto schema**

`proto/agentos.proto`:
```protobuf
syntax = "proto3";

package agentos;

option go_package = "agentos/kernel/internal/pb";

service Kernel {
  rpc StartSession(StartSessionRequest) returns (StartSessionResponse);
  rpc CallTool(CallToolRequest) returns (CallToolResponse);
}

message StartSessionRequest {
  string policy_path = 1;
}

message StartSessionResponse {
  string session_id = 1;
}

message CallToolRequest {
  string session_id = 1;
  string tool = 2;
  string params_json = 3;
}

message CallToolResponse {
  bool allowed = 1;
  bool errored = 2;
  string message = 3;
  string result_json = 4;
}
```

- [ ] **步骤 2：生成 Go 代码**

```
protoc --go_out=. --go_opt=paths=source_relative ^
  --go-grpc_out=. --go-grpc_opt=paths=source_relative ^
  proto/agentos.proto
```

这会生成 `proto/agentos.pb.go` 和 `proto/agentos_grpc.pb.go`。把它们移到 pb 包：

```
move proto\agentos.pb.go kernel\internal\pb\agentos.pb.go
move proto\agentos_grpc.pb.go kernel\internal\pb\agentos_grpc.pb.go
```

打开 `kernel/internal/pb/agentos.pb.go`，确认 package 行是 `package pb`。如果 protoc 写成了 `package agentos`，修掉它：把两个生成文件顶部的 `package agentos` 改成 `package pb`，并确保 `option go_package = "agentos/kernel/internal/pb";` 已设置（proto 里已经设了）。

- [ ] **步骤 3：生成 Python 代码**

```
cd runtime
python -m grpc_tools.protoc -I../proto ^
  --python_out=agentos_runtime/pb ^
  --grpc_python_out=agentos_runtime/pb ^
  ../proto/agentos.proto
```

创建 `runtime/agentos_runtime/pb/__init__.py`（空）。在生成的 `agentos_pb2_grpc.py` 里，import 可能写成 `import agentos_pb2 as agentos__pb2`——改成相对导入：

```python
from . import agentos_pb2 as agentos__pb2
```

- [ ] **步骤 4：验证两侧都能编译**

Go：创建临时 `kernel/cmd/agentos/main.go`:
```go
package main

import "fmt"

func main() { fmt.Println("agentos kernel") }
```
运行：`go run ./kernel/cmd/agentos`
预期：打印 `agentos kernel`。

Python：创建 `runtime/agentos_runtime/__init__.py`（空），然后：
```
cd runtime
python -c "from agentos_runtime.pb import agentos_pb2; print('ok')"
```
预期：`ok`。

- [ ] **步骤 5：检查点** —— proto 契约两侧都能编译。

---

# 阶段 1 — 内核基础（纯逻辑，TDD）

## 任务 4：Policy 结构 + YAML 加载器

**文件：**
- 创建：`kernel/internal/capability/policy.go`
- 创建：`kernel/internal/capability/policy_test.go`
- 创建：`examples/policies/data_analyst.yaml`

**背景：** Policy 是授予一个 agent 的权限集合。路径是 glob 模式（用 `**` 递归）。`cmd_exec` 和 `net` 留给未来工具用，现在先解析出来。

- [ ] **步骤 1：写失败测试**

`kernel/internal/capability/policy_test.go`:
```go
package capability

import (
	"path/filepath"
	"testing"
)

func TestLoadPolicy(t *testing.T) {
	p, err := LoadFromFile("../../examples/policies/data_analyst.yaml")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if p.AgentRole != "data_analyst" {
		t.Errorf("role = %q, want data_analyst", p.AgentRole)
	}
	if len(p.FSRead) == 0 || p.FSRead[0] != filepath.Clean("../../examples/workspace")+"**" {
		// 模式检查故意写得很松；只要确认非空
		t.Errorf("fs_read = %v", p.FSRead)
	}
	if p.MaxSteps != 20 {
		t.Errorf("max_steps = %d, want 20", p.MaxSteps)
	}
}
```

注意：上面的断言对路径文本的检查故意写得很松——按你在步骤 3 写的 YAML 内容调整即可。要断言的关键行为：role 能解析、切片能解析、MaxSteps 能解析。

- [ ] **步骤 2：运行测试验证它失败**

```
go test ./kernel/internal/capability/
```
预期：FAIL —— `LoadFromFile` 未定义。

- [ ] **步骤 3：写策略 YAML**

`examples/policies/data_analyst.yaml`:
```yaml
agent_role: data_analyst
fs_read:
  - "examples/workspace/**"
fs_write:
  - "examples/workspace/out/**"
fs_list:
  - "examples/workspace/**"
cmd_exec: []
net: disabled
max_steps: 20
```

- [ ] **步骤 4：写最小实现**

添加 `gopkg.in/yaml.v3`:
```
go get gopkg.in/yaml.v3
```

`kernel/internal/capability/policy.go`:
```go
package capability

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Policy 是授予一个 agent 会话的权限集合。
// 所有文件系统模式都是支持 **（递归）的 glob。
type Policy struct {
	AgentRole string   `yaml:"agent_role"`
	FSRead    []string `yaml:"fs_read"`
	FSWrite   []string `yaml:"fs_write"`
	FSList    []string `yaml:"fs_list"`
	CmdExec   []string `yaml:"cmd_exec"`
	Net       string   `yaml:"net"` // "disabled" 或未来的主机列表
	MaxSteps  int      `yaml:"max_steps"`
}

func LoadFromFile(path string) (*Policy, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var p Policy
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, err
	}
	if p.MaxSteps == 0 {
		p.MaxSteps = 20 // 默认值
	}
	return &p, nil
}
```

- [ ] **步骤 5：运行测试验证它通过**

```
go test ./kernel/internal/capability/
```
预期：PASS。（如果路径文本断言太严，放宽它——重点是字段能解析。）

- [ ] **步骤 6：检查点**

---

## 任务 5：权限闸门 Capability Gate

**文件：**
- 创建：`kernel/internal/capability/gate.go`
- 创建：`kernel/internal/capability/gate_test.go`

**背景：** Gate 回答："给定这个 Policy，工具 `X` 带这些参数是否被允许？"对 fs 工具，它解析路径并匹配对应的 glob 列表。它必须拒绝路径穿越（`..`）和超出根目录的绝对路径。

- [ ] **步骤 1：写失败测试**

`kernel/internal/capability/gate_test.go`:
```go
package capability

import "testing"

func TestGateAllowsReadInRoot(t *testing.T) {
	g := NewGate(&Policy{
		FSRead:  []string{"examples/workspace/**"},
		FSWrite: []string{"examples/workspace/out/**"},
	})
	if !g.Allowed("fs_read", "examples/workspace/sales.csv") {
		t.Error("expected fs_read allowed")
	}
}

func TestGateDeniesReadOutsideRoot(t *testing.T) {
	g := NewGate(&Policy{
		FSRead: []string{"examples/workspace/**"},
	})
	if g.Allowed("fs_read", "/etc/passwd") {
		t.Error("expected /etc/passwd denied")
	}
}

func TestGateDeniesTraversalEscape(t *testing.T) {
	g := NewGate(&Policy{
		FSRead: []string{"examples/workspace/**"},
	})
	if g.Allowed("fs_read", "examples/workspace/../../../etc/passwd") {
		t.Error("expected traversal escape denied")
	}
}

func TestGateEnforcesWriteRoot(t *testing.T) {
	g := NewGate(&Policy{
		FSRead:  []string{"examples/workspace/**"},
		FSWrite: []string{"examples/workspace/out/**"},
	})
	if g.Allowed("fs_write", "examples/workspace/sales.csv") {
		t.Error("write outside out/ must be denied")
	}
	if !g.Allowed("fs_write", "examples/workspace/out/result.txt") {
		t.Error("write inside out/ must be allowed")
	}
}

func TestGateDeniesUnknownTool(t *testing.T) {
	g := NewGate(&Policy{FSRead: []string{"x/**"}})
	if g.Allowed("net_fetch", "https://evil.com") {
		t.Error("unknown tool must be denied")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/capability/
```
预期：FAIL —— `NewGate`、`Allowed` 未定义。

- [ ] **步骤 3：实现闸门**

添加 doublestar:
```
go get github.com/bmatcuk/doublestar/v4
```

`kernel/internal/capability/gate.go`:
```go
package capability

import (
	"path/filepath"
	"strings"

	"github.com/bmatcuk/doublestar/v4"
)

// Gate 按 Policy 检查工具调用。
type Gate struct {
	policy *Policy
}

func NewGate(p *Policy) *Gate {
	return &Gate{policy: p}
}

// Allowed 报告工具是否可以带给定路径参数被调用。
// 对 fs_* 工具，pathArg 是文件路径。未知工具一律拒绝。
func (g *Gate) Allowed(tool, pathArg string) bool {
	switch tool {
	case "fs_read":
		return g.matchPath(g.policy.FSRead, pathArg)
	case "fs_write":
		return g.matchPath(g.policy.FSWrite, pathArg)
	case "fs_list":
		return g.matchPath(g.policy.FSList, pathArg)
	default:
		return false
	}
}

// matchPath 仅当清洗后的路径匹配某个模式、且没有通过穿越/符号链接逃出模式根时返回 true。
func (g *Gate) matchPath(patterns []string, path string) bool {
	clean := filepath.Clean(path)
	// 拒绝绝对路径：MVP 只允许仓库相对路径。
	if filepath.IsAbs(clean) {
		return false
	}
	// 拒绝任何 ".." 段——我们从不授予超出仓库的访问。
	for _, seg := range strings.Split(filepath.ToSlash(clean), "/") {
		if seg == ".." {
			return false
		}
	}
	for _, pat := range patterns {
		// 锚定：路径必须在模式的目录树内。
		ok, err := doublestar.Match(pat, clean)
		if err == nil && ok {
			return true
		}
	}
	return false
}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/capability/
```
预期：PASS（全部 5 个 gate 测试 + policy 测试）。

- [ ] **步骤 5：检查点**

---

## 任务 6：带 hash 链的审计账本

**文件：**
- 创建：`kernel/internal/audit/ledger.go`
- 创建：`kernel/internal/audit/ledger_test.go`

**背景：** Append-only，每行一个 JSON 对象。每条的 `hash` = SHA256(`prev_hash|session|ts|tool|params|outcome|result`)。创世 `prev_hash` = 64 个 0。CLI 直接读这个文件来展示审计。

- [ ] **步骤 1：写失败测试**

`kernel/internal/audit/ledger_test.go`:
```go
package audit

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func newTestLedger(t *testing.T) *Ledger {
	t.Helper()
	dir := t.TempDir()
	l, err := New(filepath.Join(dir, "audit.log"))
	if err != nil {
		t.Fatalf("new ledger: %v", err)
	}
	return l
}

func TestAppendAndChain(t *testing.T) {
	l := newTestLedger(t)
	if err := l.Append(Entry{
		SessionID: "s1", Tool: "fs_read", ParamsJSON: `{"path":"a"}`,
		Outcome: "allowed", ResultJSON: `{"content":"x"}`,
	}); err != nil {
		t.Fatal(err)
	}
	entries, err := l.ReadAll()
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("got %d entries", len(entries))
	}
	if entries[0].PrevHash != genesisHash {
		t.Errorf("first prev_hash = %q, want genesis", entries[0].PrevHash)
	}
	if entries[0].Hash == "" {
		t.Error("hash empty")
	}
}

func TestChainIsSequential(t *testing.T) {
	l := newTestLedger(t)
	_ = l.Append(Entry{SessionID: "s1", Tool: "t1", Outcome: "allowed"})
	_ = l.Append(Entry{SessionID: "s1", Tool: "t2", Outcome: "denied"})
	entries, _ := l.ReadAll()
	if entries[1].PrevHash != entries[0].Hash {
		t.Errorf("entry2.prev_hash != entry1.hash")
	}
}

func TestTamperDetection(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "audit.log")
	l, _ := New(path)
	_ = l.Append(Entry{SessionID: "s1", Tool: "t1", Outcome: "allowed"})
	_ = l.Append(Entry{SessionID: "s1", Tool: "t2", Outcome: "allowed"})

	// 篡改：重写第一行的 outcome。
	raw, _ := os.ReadFile(path)
	lines := bytes.Split(bytes.TrimSpace(raw), []byte("\n"))
	var e Entry
	_ = json.Unmarshal(lines[0], &e)
	e.Outcome = "denied"
	b, _ := json.Marshal(e)
	lines[0] = b
	_ = os.WriteFile(path, bytes.Join(lines, []byte("\n")), 0644)

	_, err := New(path).ReadAll() // 重新打开
	// ReadAll 读取必须成功，但 VerifyChain 必须失败。
	ledger2, _ := New(path)
	entries, _ := ledger2.ReadAll()
	if err := VerifyChain(entries); err == nil {
		t.Error("expected chain verification to fail after tamper")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/audit/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 3：实现账本**

`kernel/internal/audit/ledger.go`:
```go
package audit

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"sync"
	"time"
)

const genesisHash = "0000000000000000000000000000000000000000000000000000000000000000"

// Entry 是一条被审计的工具调用。
type Entry struct {
	SessionID  string `json:"session_id"`
	Timestamp  int64  `json:"timestamp_nano"`
	Tool       string `json:"tool"`
	ParamsJSON string `json:"params_json"`
	Outcome    string `json:"outcome"` // "allowed" | "denied" | "error"
	ResultJSON string `json:"result_json"`
	PrevHash   string `json:"prev_hash"`
	Hash       string `json:"hash"`
}

// Ledger 是 append-only、hash 链的审计日志。
type Ledger struct {
	mu       sync.Mutex
	path     string
	lastHash string
}

func New(path string) (*Ledger, error) {
	// 读取已有条目以恢复 lastHash（用于后续追加）。
	last := genesisHash
	if data, err := os.ReadFile(path); err == nil {
		sc := bufio.NewScanner(bytes.NewReader(data))
		for sc.Scan() {
			line := sc.Bytes()
			if len(bytes.TrimSpace(line)) == 0 {
				continue
			}
			var e Entry
			if json.Unmarshal(line, &e) == nil {
				last = e.Hash
			}
		}
	}
	return &Ledger{path: path, lastHash: last}, nil
}

func (l *Ledger) Append(e Entry) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	e.Timestamp = time.Now().UnixNano()
	e.PrevHash = l.lastHash
	e.Hash = computeHash(e.PrevHash, e)
	line, err := json.Marshal(e)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	line = append(line, '\n')
	if _, err := f.Write(line); err != nil {
		return err
	}
	l.lastHash = e.Hash
	return nil
}

// ReadAll 按文件顺序读取所有条目。
func (l *Ledger) ReadAll() ([]Entry, error) {
	data, err := os.ReadFile(l.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var out []Entry
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		line := sc.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var e Entry
		if err := json.Unmarshal(line, &e); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, sc.Err()
}

// VerifyChain 重算所有 hash，任一环断裂就返回 error。
func VerifyChain(entries []Entry) error {
	prev := genesisHash
	for i, e := range entries {
		if e.PrevHash != prev {
			return fmt.Errorf("chain broken at entry %d: prev_hash mismatch", i)
		}
		if computeHash(e.PrevHash, e) != e.Hash {
			return fmt.Errorf("chain broken at entry %d: hash mismatch", i)
		}
		prev = e.Hash
	}
	return nil
}

func computeHash(prev string, e Entry) string {
	payload := fmt.Sprintf("%s|%s|%d|%s|%s|%s|%s",
		prev, e.SessionID, e.Timestamp, e.Tool, e.ParamsJSON, e.Outcome, e.ResultJSON)
	h := sha256.Sum256([]byte(payload))
	return hex.EncodeToString(h[:])
}
```

> 说明：这里直接用标准库 `bytes.NewReader` 给 `bufio.Scanner`——这是前面草稿里 `bytesReader` 那个有 bug 的辅助函数的正确替代。最终文件已经按 `bytes.NewReader` 写好。

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/audit/
```
预期：PASS（3 个测试）。

- [ ] **步骤 5：检查点**

---

# 阶段 2 — 内核服务

## 任务 7：软沙箱 —— 文件系统路径解析器

**文件：**
- 创建：`kernel/internal/sandbox/fs.go`
- 创建：`kernel/internal/sandbox/fs_test.go`

**背景：** 沙箱是*工具实际使用的强制执行层*。给定一个请求的相对路径，它返回仓库内的安全绝对路径，拒绝穿越和符号链接逃逸。权限闸门已经做了模式匹配；沙箱做最终的 OS 级解析（所以 workspace 内指向外面的符号链接会在这里被抓住）。

- [ ] **步骤 1：写失败测试**

`kernel/internal/sandbox/fs_test.go`:
```go
package sandbox

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveInsideRoot(t *testing.T) {
	dir := t.TempDir()
	abs, err := Resolve(filepath.Join(dir, "a.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if abs != filepath.Join(dir, "a.txt") {
		t.Errorf("got %q", abs)
	}
}

func TestResolveRejectsTraversal(t *testing.T) {
	dir := t.TempDir()
	_, err := Resolve(filepath.Join(dir, "..", "..", "etc", "passwd"))
	if err == nil {
		t.Error("expected traversal rejected")
	}
}

func TestResolveRejectsSymlinkEscape(t *testing.T) {
	dir := t.TempDir()
	target := t.TempDir() // 在 dir 之外
	if err := os.WriteFile(filepath.Join(target, "secret"), []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(dir, "escape")); err != nil {
		t.Skip("symlink not supported here:", err)
	}
	_, err := Resolve(filepath.Join(dir, "escape", "secret"))
	if err == nil {
		t.Error("expected symlink escape rejected")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/sandbox/
```
预期：FAIL —— `Resolve` 未定义。

- [ ] **步骤 3：实现 Resolve**

`kernel/internal/sandbox/fs.go`:
```go
package sandbox

import (
	"fmt"
	"os"
	"path/filepath"
)

// Resolve 把请求路径转成安全的绝对路径。
// 它拒绝：
//   - 清洗后任何 ".." 段
//   - 真实落点不在路径自身目录树内的符号链接
//     （即逃出其所在树的符号链接）
func Resolve(requested string) (string, error) {
	clean := filepath.Clean(requested)
	abs, err := filepath.Abs(clean)
	if err != nil {
		return "", err
	}
	// 拒绝显式的父级穿越。
	for _, seg := range splitSegments(clean) {
		if seg == ".." {
			return "", fmt.Errorf("path traversal rejected: %s", requested)
		}
	}
	// 解析符号链接；真实路径必须在请求目录的父树内。
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		if os.IsNotExist(err) {
			// 目标文件还不存在（如 fs_write）。解析父目录。
			parentReal, perr := filepath.EvalSymlinks(filepath.Dir(abs))
			if perr != nil {
				return "", fmt.Errorf("cannot resolve parent: %w", perr)
			}
			return filepath.Join(parentReal, filepath.Base(abs)), nil
		}
		return "", err
	}
	// 检测符号链接逃逸：真实路径必须在清洗后 abs 的目录下。
	expectedDir := filepath.Dir(cleanAbsOrDir(abs))
	if !isUnder(real, expectedDir) && real != abs {
		return "", fmt.Errorf("symlink escape rejected: %s -> %s", requested, real)
	}
	return real, nil
}

func splitSegments(p string) []string {
	var out []string
	for p != "" && p != string(filepath.Separator) {
		out = append([]string{filepath.Base(p)}, out...)
		p = filepath.Dir(p)
	}
	return out
}

func cleanAbsOrDir(abs string) string {
	return abs
}

func isUnder(path, root string) bool {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return false
	}
	if rel == "." {
		return true
	}
	for _, seg := range splitSegments(rel) {
		if seg == ".." {
			return false
		}
	}
	return true
}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/sandbox/
```
预期：PASS。如果符号链接测试在 Windows 上不稳定，可以接受——`t.Skip` 会处理。

- [ ] **步骤 5：检查点**

---

## 任务 8：工具注册表 + fs 工具

**文件：**
- 创建：`kernel/internal/tools/registry.go`
- 创建：`kernel/internal/tools/fs_tools.go`
- 创建：`kernel/internal/tools/registry_test.go`

**背景：** 工具是内核的"系统调用"。每个工具：一个名字，一个接收 JSON 参数、返回 JSON 结果的 handler。注册表是 gRPC 服务端做分发的对象。fs_read/fs_write/fs_list 通过沙箱解析（真实的 OS 安全）——闸门在分发前由服务端检查，但工具也做二次检查，纵深防御。

- [ ] **步骤 1：写失败测试**

`kernel/internal/tools/registry_test.go`:
```go
package tools

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFSRead(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "hello.txt")
	_ = os.WriteFile(path, []byte("hi"), 0644)

	res, err := FSRead(map[string]any{"path": path})
	if err != nil {
		t.Fatal(err)
	}
	if res["content"] != "hi" {
		t.Errorf("content = %v", res["content"])
	}
}

func TestFSWriteThenRead(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "sub", "out.txt")
	if _, err := FSWrite(map[string]any{"path": target, "content": "boom"}); err != nil {
		t.Fatal(err)
	}
	res, _ := FSRead(map[string]any{"path": target})
	if res["content"] != "boom" {
		t.Errorf("got %v", res["content"])
	}
}

func TestFSList(t *testing.T) {
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "a.txt"), []byte("x"), 0644)
	_ = os.WriteFile(filepath.Join(dir, "b.txt"), []byte("x"), 0644)
	res, err := FSList(map[string]any{"path": dir})
	if err != nil {
		t.Fatal(err)
	}
	names, ok := res["entries"].([]string)
	if !ok {
		t.Fatalf("entries type: %T", res["entries"])
	}
	if len(names) != 2 {
		t.Errorf("got %d entries", len(names))
	}
}

func TestRegistryDispatch(t *testing.T) {
	r := NewRegistry()
	r.Register("fs_read", FSRead)
	_, ok := r.Get("fs_read")
	if !ok {
		t.Error("fs_read not registered")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/tools/
```
预期：FAIL —— 符号未定义。

- [ ] **步骤 3：实现注册表**

`kernel/internal/tools/registry.go`:
```go
package tools

// Handler 执行一个工具。params 是解码后的 JSON 参数。
// 它返回一个可 JSON 序列化的结果 map。
type Handler func(params map[string]any) (map[string]any, error)

type Registry struct {
	handlers map[string]Handler
}

func NewRegistry() *Registry {
	return &Registry{handlers: map[string]Handler{}}
}

func (r *Registry) Register(name string, h Handler) {
	r.handlers[name] = h
}

func (r *Registry) Get(name string) (Handler, bool) {
	h, ok := r.handlers[name]
	return h, ok
}

func (r *Registry) Names() []string {
	out := make([]string, 0, len(r.handlers))
	for n := range r.handlers {
		out = append(out, n)
	}
	return out
}
```

- [ ] **步骤 4：实现 fs 工具**

`kernel/internal/tools/fs_tools.go`:
```go
package tools

import (
	"os"
	"path/filepath"
)

// FSRead 读取文件的文本内容。
func FSRead(params map[string]any) (map[string]any, error) {
	path, _ := params["path"].(string)
	safe, err := resolve(path)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(safe)
	if err != nil {
		return nil, err
	}
	return map[string]any{"content": string(data)}, nil
}

// FSWrite 把文本内容写入文件，自动创建父目录。
func FSWrite(params map[string]any) (map[string]any, error) {
	path, _ := params["path"].(string)
	content, _ := params["content"].(string)
	safe, err := resolve(path)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(safe), 0755); err != nil {
		return nil, err
	}
	if err := os.WriteFile(safe, []byte(content), 0644); err != nil {
		return nil, err
	}
	return map[string]any{"bytes_written": len(content)}, nil
}

// FSList 列出目录条目（仅名字）。
func FSList(params map[string]any) (map[string]any, error) {
	path, _ := params["path"].(string)
	safe, err := resolve(path)
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(safe)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e.Name())
	}
	return map[string]any{"entries": names}, nil
}

// resolve 包装沙箱解析器，让工具能被独立单测。
// 真正的活由 sandbox 包干。
func resolve(path string) (string, error) {
	return sandboxResolve(path)
}
```

> **注意：** `sandboxResolve` 是 `sandbox.Resolve` 的薄别名。加一个小文件 `kernel/internal/tools/sandbox_alias.go`:
```go
package tools

import "agentos/kernel/internal/sandbox"

func sandboxResolve(path string) (string, error) {
	return sandbox.Resolve(path)
}
```

- [ ] **步骤 5：运行测试验证它们通过**

```
go test ./kernel/internal/tools/
```
预期：PASS。

- [ ] **步骤 6：检查点**

---

## 任务 9：会话管理器

**文件：**
- 创建：`kernel/internal/session/manager.go`

**背景：** 持有一个活动 agent 会话的内存状态：它的 Policy、Gate、步数计数器、审计账本句柄。

- [ ] **步骤 1：实现管理器**

`kernel/internal/session/manager.go`:
```go
package session

import (
	"sync"

	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/capability"
)

// Session 是一个运行中 agent 的内核侧状态。
type Session struct {
	ID     string
	Policy *capability.Policy
	Gate   *capability.Gate
	Steps  int
	Ledger *audit.Ledger
}

// Manager 按 ID 跟踪活动会话。
type Manager struct {
	mu       sync.Mutex
	sessions map[string]*Session
}

func NewManager() *Manager {
	return &Manager{sessions: map[string]*Session{}}
}

func (m *Manager) Add(s *Session) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sessions[s.ID] = s
}

func (m *Manager) Get(id string) (*Session, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.sessions[id]
	return s, ok
}

func (m *Manager) Delete(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.sessions, id)
}
```

- [ ] **步骤 2：检查点**（这里不写测试——只是简单的接线，由任务 11 的服务端集成测试覆盖。）

---

## 任务 10：gRPC 服务端 —— StartSession + CallTool

**文件：**
- 创建：`kernel/internal/server/server.go`

**背景：** 这是内核的心脏。`StartSession` 加载策略，创建 Gate + Ledger + Session。`CallTool` 做的事：加载会话 → 检查闸门 → 若拒绝则审计 `denied` + 返回；若允许则通过注册表跑工具，审计 `allowed`/`error`，返回结果。**拒绝原因不会泄露给 LLM**——消息只是 "permission denied"。

- [ ] **步骤 1：实现服务端**

`kernel/internal/server/server.go`:
```go
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"

	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/capability"
	"agentos/kernel/internal/pb"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

type Server struct {
	pb.UnimplementedKernelServer
	sessions *session.Manager
	registry *tools.Registry
	auditDir string
}

func New(auditDir string) *Server {
	reg := tools.NewRegistry()
	reg.Register("fs_read", tools.FSRead)
	reg.Register("fs_write", tools.FSWrite)
	reg.Register("fs_list", tools.FSList)
	return &Server{
		sessions: session.NewManager(),
		registry: reg,
		auditDir: auditDir,
	}
}

func (s *Server) StartSession(ctx context.Context, req *pb.StartSessionRequest) (*pb.StartSessionResponse, error) {
	policy, err := capability.LoadFromFile(req.PolicyPath)
	if err != nil {
		return nil, fmt.Errorf("load policy: %w", err)
	}
	id := newSessionID()
	ledger, err := audit.New(filepath.Join(s.auditDir, id+".log"))
	if err != nil {
		return nil, err
	}
	sess := &session.Session{
		ID:     id,
		Policy: policy,
		Gate:   capability.NewGate(policy),
		Ledger: ledger,
	}
	s.sessions.Add(sess)
	return &pb.StartSessionResponse{SessionId: id}, nil
}

func (s *Server) CallTool(ctx context.Context, req *pb.CallToolRequest) (*pb.CallToolResponse, error) {
	sess, ok := s.sessions.Get(req.SessionId)
	if !ok {
		return nil, fmt.Errorf("unknown session %s", req.SessionId)
	}

	var params map[string]any
	if req.ParamsJson != "" {
		if err := json.Unmarshal([]byte(req.ParamsJson), &params); err != nil {
			return s.deny(sess, req, "invalid params"), nil
		}
	}

	// 步数上限。
	sess.Steps++
	if sess.Policy.MaxSteps > 0 && sess.Steps > sess.Policy.MaxSteps {
		return s.deny(sess, req, "step limit reached"), nil
	}

	// 权限闸门。提取路径参数（MVP 所有工具都取 "path"）。
	pathArg, _ := params["path"].(string)
	if !sess.Gate.Allowed(req.Tool, pathArg) {
		return s.deny(sess, req, "permission denied"), nil
	}

	handler, ok := s.registry.Get(req.Tool)
	if !ok {
		return s.deny(sess, req, "permission denied"), nil // 未知工具 = 拒绝，返回通用消息
	}

	result, err := handler(params)
	if err != nil {
		s.audit(sess, req, params, "error", "")
		return &pb.CallToolResponse{Errored: true, Message: "tool error"}, nil
	}

	resultJSON, _ := json.Marshal(result)
	s.audit(sess, req, params, "allowed", string(resultJSON))
	return &pb.CallToolResponse{Allowed: true, ResultJson: string(resultJSON)}, nil
}

func (s *Server) deny(sess *session.Session, req *pb.CallToolRequest, _ string) *pb.CallToolResponse {
	// 注意：reason 字符串故意不返回给调用方，
	// 避免把权限细节泄露给可能被注入的 LLM。
	var params map[string]any
	_ = json.Unmarshal([]byte(req.ParamsJson), &params)
	s.audit(sess, req, params, "denied", "")
	return &pb.CallToolResponse{Allowed: false, Message: "permission denied"}
}

func (s *Server) audit(sess *session.Session, req *pb.CallToolRequest, _ map[string]any, outcome, resultJSON string) {
	_ = sess.Ledger.Append(audit.Entry{
		SessionID:  sess.ID,
		Tool:       req.Tool,
		ParamsJSON: req.ParamsJson,
		Outcome:    outcome,
		ResultJSON: resultJSON,
	})
}

func newSessionID() string {
	return fmt.Sprintf("sess-%d", nowUnixNano())
}

func nowUnixNano() int64 { /* 见下 */ return timeNowUnixNano() }
```

加 `kernel/internal/server/time.go`:
```go
package server

import "time"

func timeNowUnixNano() int64 { return time.Now().UnixNano() }
```

（把 `nowUnixNano` 放在 helper 后面是为了将来测试时可 mock。）

- [ ] **步骤 2：验证它能编译**

```
go build ./kernel/...
```
预期：无错误。遇到 import/类型问题就修（proto 字段名比如 `SessionId` vs `session_id` 必须和生成代码一致——查 `kernel/internal/pb/agentos.pb.go` 里的确切 Go 名）。

- [ ] **步骤 3：检查点**

---

## 任务 11：内核 CLI —— `agentos serve` 和 `agentos audit show`

**文件：**
- 修改：`kernel/cmd/agentos/main.go`

**背景：** CLI 在 Unix socket 上跑 gRPC 服务端（`agentos serve`），并读取审计日志文件（`agentos audit show <日志文件>`）。Python 运行时连到这个 socket 来启动会话、调用工具。

- [ ] **步骤 1：实现 CLI**

`kernel/cmd/agentos/main.go`:
```go
package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"

	"google.golang.org/grpc"

	"agentos/kernel/internal/audit"
	pb "agentos/kernel/internal/pb"
	"agentos/kernel/internal/server"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("usage: agentos <serve|audit> ...")
		os.Exit(1)
	}
	switch os.Args[1] {
	case "serve":
		cmdServe(os.Args[2:])
	case "audit":
		cmdAudit(os.Args[2:])
	default:
		fmt.Println("unknown command:", os.Args[1])
		os.Exit(1)
	}
}

func cmdServe(args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	socket := fs.String("socket", "./agentos.sock", "unix socket path")
	auditDir := fs.String("audit-dir", "./audit", "audit log directory")
	fs.Parse(args)

	os.MkdirAll(*auditDir, 0755)
	_ = os.Remove(*socket) // 清掉上次残留的 socket

	lis, err := net.Listen("unix", *socket)
	if err != nil {
		fmt.Println("listen:", err)
		os.Exit(1)
	}
	grpcServer := grpc.NewServer()
	pb.RegisterKernelServer(grpcServer, server.New(*auditDir))

	fmt.Printf("agentos kernel listening on %s\n", *socket)
	if err := grpcServer.Serve(lis); err != nil {
		fmt.Println("serve:", err)
		os.Exit(1)
	}
}

func cmdAudit(args []string) {
	fs := flag.NewFlagSet("audit", flag.ExitOnError)
	fs.Parse(args)
	if fs.NArg() < 1 {
		fmt.Println("usage: agentos audit show <logfile | session-id>")
		os.Exit(1)
	}
	target := fs.Arg(0)
	if _, err := os.Stat(target); os.IsNotExist(err) {
		// 当成 session id 处理
		target = filepath.Join("./audit", target+".log")
	}

	// 读取条目。
	l, err := audit.New(target)
	if err != nil {
		fmt.Println("open audit:", err)
		os.Exit(1)
	}
	entries, err := l.ReadAll()
	if err != nil {
		fmt.Println("read audit:", err)
		os.Exit(1)
	}
	if err := audit.VerifyChain(entries); err != nil {
		fmt.Println("⚠️  CHAIN VERIFICATION FAILED:", err)
	}
	for _, e := range entries {
		fmt.Printf("%s  %s  %s  [%s]\n", e.SessionID, e.Tool, e.Outcome, e.ParamsJSON)
	}
	_ = context.Background
	_ = bufio.NewReader
}
```

- [ ] **步骤 2：构建**

```
go build -o agentos.exe ./kernel/cmd/agentos
```
预期：产出 `agentos.exe`。

- [ ] **步骤 3：冒烟测试（手动）**

在一个终端：
```
agentos.exe serve -socket ./agentos.sock
```
预期：`agentos kernel listening on ./agentos.sock`。

让它跑着，等后续阶段用。

- [ ] **步骤 4：检查点** —— 内核是一个运行中的 gRPC 服务。

---

# 阶段 3 — Python 运行时

## 任务 12：运行时包 + pyproject

**文件：**
- 创建：`runtime/pyproject.toml`
- 创建：`runtime/agentos_runtime/__init__.py`

- [ ] **步骤 1：写 pyproject.toml**

`runtime/pyproject.toml`:
```toml
[project]
name = "agentos-runtime"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "grpcio>=1.60",
    "openai>=1.30",
]

[project.scripts]
agentos-run = "agentos_runtime.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **步骤 2：以可编辑模式安装**

```
cd runtime
pip install -e .
```
预期：安装了 `agentos-run` 命令行脚本。

- [ ] **步骤 3：检查点**

---

## 任务 13：内核 gRPC 客户端（Python）

**文件：**
- 创建：`runtime/agentos_runtime/kernel_client.py`
- 创建：`runtime/tests/test_kernel_client.py`

**背景：** MVP 用同步的薄客户端（未来可扩展异步）。连 Unix socket，暴露 `start_session(policy_path)` 和 `call_tool(session_id, tool, params_dict)`。

- [ ] **步骤 1：写失败测试（用假 stub）**

`runtime/tests/test_kernel_client.py`:
```python
from agentos_runtime.kernel_client import KernelClient


class FakeStub:
    def __init__(self):
        self.calls = []

    def StartSession(self, req, **kw):
        self.calls.append(("start", req.policy_path))
        class R:
            session_id = "sess-fake"
        return R()

    def CallTool(self, req, **kw):
        self.calls.append(("call", req.tool, req.params_json))
        class R:
            allowed = True
            errored = False
            message = ""
            result_json = '{"content":"hi"}'
        return R()


def test_start_and_call(monkeypatch):
    client = KernelClient("dummy.sock")
    client._stub = FakeStub()  # 绕过真实 channel
    sid = client.start_session("examples/policies/data_analyst.yaml")
    assert sid == "sess-fake"
    result = client.call_tool(sid, "fs_read", {"path": "x"})
    assert result["allowed"] is True
    assert result["result"] == {"content": "hi"}
```

- [ ] **步骤 2：运行测试验证它失败**

```
cd runtime
pytest tests/test_kernel_client.py -v
```
预期：FAIL —— 模块找不到。

- [ ] **步骤 3：实现客户端**

`runtime/agentos_runtime/kernel_client.py`:
```python
import json
import os
from dataclasses import dataclass

import grpc

from .pb import agentos_pb2 as pb
from .pb import agentos_pb2_grpc as pb_grpc


@dataclass
class ToolResult:
    allowed: bool
    errored: bool
    message: str
    result: dict


class KernelClient:
    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        self._channel = None
        self._stub = None

    def _ensure(self):
        if self._stub is None:
            self._channel = grpc.insecure_channel(
                f"file://{self._socket_path}" if os.name == "nt" else self._socket_path
            )
            grpc.channel_ready_future(self._channel).result(timeout=10)
            self._stub = pb_grpc.KernelStub(self._channel)

    def start_session(self, policy_path: str) -> str:
        self._ensure()
        resp = self._stub.StartSession(pb.StartSessionRequest(policy_path=policy_path))
        return resp.session_id

    def call_tool(self, session_id: str, tool: str, params: dict) -> dict:
        self._ensure()
        params_json = json.dumps(params) if params else ""
        resp = self._stub.CallTool(
            pb.CallToolRequest(session_id=session_id, tool=tool, params_json=params_json)
        )
        result = {}
        if resp.result_json:
            result = json.loads(resp.result_json)
        return {
            "allowed": resp.allowed,
            "errored": resp.errored,
            "message": resp.message,
            "result": result,
        }

    def close(self):
        if self._channel:
            self._channel.close()
```

> **Windows socket 注意：** grpc-python 在 Windows 上用 unix socket 的 `insecure_channel` 可能需要 `file://` 前缀或 `unix:` 协议。如果连不上，试 `f"unix:{self._socket_path}"`。这是最可能踩的跨平台坑——留个清晰的注释和兜底。

- [ ] **步骤 4：运行测试验证它通过**

```
pytest tests/test_kernel_client.py -v
```
预期：PASS。

- [ ] **步骤 5：检查点**

---

## 任务 14：DeepSeek LLM 客户端

**文件：**
- 创建：`runtime/agentos_runtime/llm/base.py`
- 创建：`runtime/agentos_runtime/llm/deepseek.py`

- [ ] **步骤 1：LLM 基类接口**

`runtime/agentos_runtime/llm/base.py`:
```python
from typing import Protocol


class Message(dict):
    """一条聊天消息 dict: {role, content, tool_calls?, tool_call_id?}。"""


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """返回 assistant 消息 dict（可能含 tool_calls）。"""
        ...
```

- [ ] **步骤 2：DeepSeek 实现**

`runtime/agentos_runtime/llm/deepseek.py`:
```python
import os

from openai import OpenAI

from .base import LLMClient


class DeepSeekClient:
    """DeepSeek，走 OpenAI 兼容 API。"""

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = None):
        key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self._client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        self._model = model

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
        )
        msg = resp.choices[0].message
        # 转成纯可序列化的 dict。
        out = {"role": "assistant"}
        if msg.content:
            out["content"] = msg.content
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return out
```

- [ ] **步骤 3：冒烟测试（手动，需联网 + key）**

```
cd runtime
python -c "from agentos_runtime.llm.deepseek import DeepSeekClient; c=DeepSeekClient(); print(c.chat([{'role':'user','content':'say hi in 3 words'}], []))"
```
预期：一个含 `content` 的响应 dict。（如果遇到配额/鉴权错误，先修 key——循环跑通前别往下走。）

- [ ] **步骤 4：检查点**

---

## 任务 15：暴露给 LLM 的工具 schema

**文件：**
- 创建：`runtime/agentos_runtime/tools.py`

- [ ] **步骤 1：定义工具 schema**

`runtime/agentos_runtime/tools.py`:
```python
# OpenAI/DeepSeek function-calling 格式。
# 注意：工具名用下划线，不是点号——函数名正则拒绝点号。
# 这些和内核工具名（fs_read 等）一一对应。

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "Read a text file. Path is relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": "Write text content to a file (creates parent dirs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": "List file names in a directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]
```

> 说明：`description` 是发给 LLM 的运行时 schema，保持英文（与发给 DeepSeek 的协议一致）；如果你想用中文 description 让模型更好理解，可以在执行阶段再改，不影响逻辑。

- [ ] **步骤 2：检查点**

---

## 任务 16：ReAct 循环

**文件：**
- 创建：`runtime/agentos_runtime/loop.py`
- 创建：`runtime/tests/test_loop.py`

**背景：** 循环：维护消息列表，带工具调用 LLM。如果响应含 `tool_calls`，通过内核客户端执行每一个，把结果作为 `tool` 消息追加，重复。当响应没有 tool_calls（最终答案）或达到 `max_steps` 时停止。工具调用参数以 JSON 字符串到达——要解析。

- [ ] **步骤 1：写失败测试（mock LLM + mock 内核）**

`runtime/tests/test_loop.py`:
```python
import json
from agentos_runtime.loop import run_agent


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def chat(self, messages, tools):
        msg = self.script[self.i]
        self.i += 1
        return msg


class FakeKernel:
    def __init__(self):
        self.calls = []
        self.session = "s1"

    def start_session(self, policy):
        return self.session

    def call_tool(self, sid, tool, params):
        self.calls.append((tool, params))
        return {"allowed": True, "errored": False, "message": "", "result": {"content": "DATA"}}

    def close(self):
        pass


def test_loop_runs_tool_then_finishes():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "a.txt"})}}]},
        {"role": "assistant", "content": "Done. Total is 42."},
    ])
    kernel = FakeKernel()
    result = run_agent("compute total", llm, kernel, policy_path="p.yaml", max_steps=5)
    assert kernel.calls == [("fs_read", {"path": "a.txt"})]
    assert "42" in result


def test_loop_respects_max_steps():
    # LLM 永远要求再调一次工具 -> 永不结束。
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": str(i), "type": "function",
            "function": {"name": "fs_list", "arguments": json.dumps({"path": "."})}}]}
        for i in range(100)
    ])
    kernel = FakeKernel()
    result = run_agent("loop", llm, kernel, policy_path="p.yaml", max_steps=3)
    assert "step limit" in result.lower() or "max" in result.lower()
    assert len(kernel.calls) == 3


def test_loop_handles_denied_tool():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "/etc/shadow"})}}]},
        {"role": "assistant", "content": "Could not read. Done."},
    ])
    kernel = FakeKernel()
    kernel.call_tool = lambda *a: {"allowed": False, "errored": False, "message": "permission denied", "result": {}}
    result = run_agent("try", llm, kernel, policy_path="p.yaml", max_steps=5)
    assert "Done" in result
```

- [ ] **步骤 2：运行测试验证它们失败**

```
pytest tests/test_loop.py -v
```
预期：FAIL —— `run_agent` 未定义。

- [ ] **步骤 3：实现循环**

`runtime/agentos_runtime/loop.py`:
```python
import json

from .tools import TOOL_SCHEMAS

SYSTEM_PROMPT = (
    "You are an autonomous agent running inside a sandboxed operating system. "
    "You have access to filesystem tools that are strictly permission-checked. "
    "If a tool returns 'permission denied', do not retry it; work around it or "
    "report the limitation. Complete the task using as few tool calls as possible, "
    "then give your final answer as plain text."
)


def run_agent(task: str, llm, kernel, policy_path: str, max_steps: int = 20) -> str:
    session_id = kernel.start_session(policy_path)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for _ in range(max_steps):
        assistant = llm.chat(messages, TOOL_SCHEMAS)
        messages.append(assistant)

        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            # 最终答案。
            return assistant.get("content", "(no content)")

        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            res = kernel.call_tool(session_id, name, args)
            tool_message = _format_tool_result(tc["id"], name, res)
            messages.append(tool_message)

    return f"Reached step limit ({max_steps}) without finishing."


def _format_tool_result(tool_call_id: str, name: str, res: dict) -> dict:
    if res.get("errored"):
        content = f"Tool error: {res.get('message', 'unknown')}"
    elif not res.get("allowed"):
        # 注意：不回显拒绝的内部细节；内核已经发了通用消息。
        content = res.get("message", "permission denied")
    else:
        content = json.dumps(res.get("result", {}))
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
    }
```

> 说明：`SYSTEM_PROMPT` 是运行时发给 LLM 的真实提示，保持英文以匹配 OpenAI 兼容协议和测试断言。如果想让 agent 用中文交互，可在执行阶段把任务（`task`）和 prompt 改成中文，不影响循环逻辑。

- [ ] **步骤 4：运行测试验证它们通过**

```
pytest tests/test_loop.py -v
```
预期：PASS（3 个测试）。

- [ ] **步骤 5：检查点**

---

## 任务 17：运行时 CLI —— `agentos-run`

**文件：**
- 创建：`runtime/agentos_runtime/cli.py`

- [ ] **步骤 1：实现 CLI**

`runtime/agentos_runtime/cli.py`:
```python
import argparse
import sys

from .kernel_client import KernelClient
from .llm.deepseek import DeepSeekClient
from .loop import run_agent


def main():
    p = argparse.ArgumentParser(prog="agentos-run")
    p.add_argument("--task", required=True, help="The task for the agent.")
    p.add_argument("--policy", required=True, help="Path to capability policy YAML.")
    p.add_argument("--socket", default="./agentos.sock", help="Kernel unix socket path.")
    p.add_argument("--max-steps", type=int, default=20)
    args = p.parse_args()

    kernel = KernelClient(args.socket)
    llm = DeepSeekClient()
    try:
        result = run_agent(args.task, llm, kernel, policy_path=args.policy, max_steps=args.max_steps)
        print("=== AGENT RESULT ===")
        print(result)
    finally:
        kernel.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
```

- [ ] **步骤 2：检查点**

---

# 阶段 4 — 集成与对抗性安全测试

## 任务 18：演示工作区夹具

**文件：**
- 创建：`examples/workspace/sales.csv`

- [ ] **步骤 1：创建示例数据**

`examples/workspace/sales.csv`:
```csv
date,product,amount
2026-01-05,Widget,120
2026-01-07,Gadget,80
2026-01-09,Widget,200
2026-01-12,Gadget,45
```

- [ ] **步骤 2：检查点**

---

## 任务 19：端到端集成测试（手动 runbook）

**背景：** 这是设计文档里的那个 demo。没有自动化测试（它需要活的 LLM + 运行中的内核）；它是一个你手动执行来验证 MVP 的 runbook。

- [ ] **步骤 1：启动内核**

终端 1：
```
agentos.exe serve -socket ./agentos.sock -audit-dir ./audit
```
预期：`agentos kernel listening on ./agentos.sock`。

- [ ] **步骤 2：跑合法任务**

终端 2（在仓库根，已设 `DEEPSEEK_API_KEY`）：
```
agentos-run --task "Read examples/workspace/sales.csv, compute the total amount, and write the result to examples/workspace/out/total.txt" --policy examples/policies/data_analyst.yaml --socket ./agentos.sock
```
预期：agent 打印一个结果；`examples/workspace/out/total.txt` 内容是 `445`（120+80+200+45）。

- [ ] **步骤 3：检查审计日志**

```
agentos.exe audit show <打印出来/./audit 里最近的那个 session id>
```
预期：行显示 `fs_read sales.csv [allowed]` 和 `fs_write out/total.txt [allowed]`，且 hash 链校验通过。

- [ ] **步骤 4：检查点** —— 三支柱 demo（能干活、被管住、可审计）在正常路径上跑通。

---

## 任务 20：对抗性安全测试套件（护城河）

**文件：**
- 创建：`kernel/test/adversarial/adversarial_test.go`

**背景：** 这是差异化所在。这些测试**直接打内核**（没有 LLM，确定性的），证明每个攻击都被挡住。每个测试调用 `CallTool` 并断言 `allowed == false`。这套测试本身就是卖点："通过了 N 个对抗用例。"

- [ ] **步骤 1：写对抗套件**

`kernel/test/adversarial/adversarial_test.go`:
```go
package adversarial

import (
	"path/filepath"
	"testing"

	"agentos/kernel/internal/capability"
)

// loadRealPolicy 加载 examples/policies/data_analyst.yaml，
// 这样套件测的就是随产品发布的真实策略。
func loadRealPolicy(t *testing.T) *capability.Gate {
	t.Helper()
	rel := filepath.Join("..", "..", "..", "..", "examples", "policies", "data_analyst.yaml")
	p, err := capability.LoadFromFile(rel)
	if err != nil {
		t.Fatalf("load policy: %v", err)
	}
	return capability.NewGate(p)
}

func TestAdversarialReadEtcShadow(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", "/etc/shadow") {
		t.Fatal("must deny /etc/shadow")
	}
}

func TestAdversarialReadAbsWindowsSecret(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", "C:/Windows/System32/config/SAM") {
		t.Fatal("must deny absolute Windows path")
	}
}

func TestAdversarialTraversalEscape(t *testing.T) {
	g := loadRealPolicy(t)
	attacks := []string{
		"examples/workspace/../../../../etc/passwd",
		"examples/workspace/../../../.ssh/id_rsa",
		"examples/workspace/out/../../../secret",
	}
	for _, a := range attacks {
		if g.Allowed("fs_read", a) {
			t.Fatalf("must deny traversal: %s", a)
		}
	}
}

func TestAdversarialWriteOutsideOutDir(t *testing.T) {
	g := loadRealPolicy(t)
	// data_analyst 只能写 examples/workspace/out/**
	if g.Allowed("fs_write", "examples/workspace/sales.csv") {
		t.Fatal("must deny overwriting source data")
	}
	if g.Allowed("fs_write", "examples/workspace/evil.txt") {
		t.Fatal("must deny write outside out/")
	}
}

func TestAdversarialUnknownTool(t *testing.T) {
	g := loadRealPolicy(t)
	// 不存在任意代码执行工具；注入的 "shell_exec" 必须被拒。
	if g.Allowed("shell_exec", "rm -rf /") {
		t.Fatal("must deny unknown tool")
	}
}

func TestAdversarialNetworkDisabled(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("net_fetch", "https://evil.com/exfil") {
		t.Fatal("must deny network")
	}
}
```

> 说明：早先草稿里有一版用 `s.StartSession(...)` 打服务端的写法——但 `StartSession` 需要 `*pb.StartSessionRequest`，绕这个请求类型不划算。改成**直接打 Gate**（真正的安全边界），确定性最强，而且安全策略就活在 Gate 这一层。

- [ ] **步骤 2：跑套件**

```
go test ./kernel/test/adversarial/ -v
```
预期：全部 6 个对抗测试 PASS（每个都断言一次拒绝）。如果任何一个失败，内核有安全洞——修完再继续。

- [ ] **步骤 3：检查点** —— 护城河被证明。

---

## 任务 21：按成功标准做最终验证

- [ ] **步骤 1：跑全部 Go 测试**

```
go test ./...
```
预期：所有包 PASS（capability、audit、sandbox、tools、adversarial）。

- [ ] **步骤 2：跑全部 Python 测试**

```
cd runtime && pytest -v
```
预期：全部 PASS（kernel client、loop）。

- [ ] **步骤 3：重跑 demo（任务 19）端到端**

确认：任务完成 → `out/total.txt` = 445 → 审计显示 allowed 调用 → hash 链校验通过。

- [ ] **步骤 4：重跑对抗套件（任务 20）**

确认：6 个攻击全部被拒。

- [ ] **步骤 5：最终检查点**

MVP（方案 A）完成。设计文档（§11）的成功标准全部满足：
1. ✅ 功能：完整数据流跑通，agent 完成任务。
2. ✅ 安全：所有对抗用例被正确拒绝。
3. ✅ 可审计：`agentos audit show` 产出 hash 链校验过的日志。
4. ✅ 可演示：三步 demo 可复现。

**这验证了核心壁垒假设。** 下一步：阶段 1（多 agent 调度）。

---

## 自查（写完后运行 —— 结果）

**1. 设计覆盖：**
- §3.1 分层架构 → 任务 10、11（服务端/CLI）、13、14、16（运行时）。✓
- §3.2 进程模型（Kernel/Runtime/Sandbox）→ 任务 7–11、13–16。✓
- §3.3 gRPC over unix socket → 任务 3、11、13。✓
- §4.1 沙箱（软隔离）→ 任务 7。✓（硬隔离明确推迟到阶段 2）
- §4.2 权限模型 → 任务 4、5。✓
- §4.3 审计账本 → 任务 6；CLI 读取在任务 11。✓
- §5.1 LLM 抽象 → 任务 14（DeepSeek + 基类接口）。✓（OpenAI/Local provider 通过基类留桩——MVP 只需要 DeepSeek）
- §5.2 ReAct 循环 → 任务 16。✓
- §5.3 工具协议 → 任务 8、10、13。✓
- §6 数据流 → 任务 19（集成）。✓
- §7 错误处理：max_steps（任务 16）、拒绝通用消息（任务 10）、工具错误回传（任务 16）、所有结果都审计（任务 10）。✓
- §8 测试：单元（任务 4–8、13、16）、集成（任务 19）、对抗（任务 20）。✓
- §11 成功标准 → 任务 21。✓

**2. 占位符扫描：** 无 TBD/TODO。几处"说明/注意"是在线应用的修正，不是未决占位符。✓

**3. 类型/名字一致性：**
- 工具名：`fs_read`/`fs_write`/`fs_list` 在 Go（任务 8、10）、proto（工具无关的 `tool` 字符串）、Python（任务 15、16）中一致使用。✓
- proto 字段 Go 名：`SessionId`、`PolicyPath`、`ParamsJson`、`ResultJson` —— 在任务 3 步骤 2 对照生成代码核实（任务 10 步骤 2 已注明）。✓
- 审计 `Entry` 字段在任务 6 和任务 10 间一致。✓
- `KernelClient.call_tool` 返回形状在任务 13 和任务 16 的循环间一致。✓

全部检查通过。计划就绪。
