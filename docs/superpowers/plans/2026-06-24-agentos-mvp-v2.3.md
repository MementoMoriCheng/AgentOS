# AgentOS MVP 实现计划 v2.3（阶段 0 — 安全内核，数据分析场景）

> **给执行 agent：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 来逐任务执行本计划。步骤用 checkbox（`- [ ]`）语法跟踪。

**目标：** 构建 MVP 安全内核（v2.3）——一个 agent 在脱敏 + 权限受控 + 可审计的 Pipeline 里跑通数据分析任务，验证技术架构与安全机制，并证明"加新工具时 Kernel 核心零改动"。

**架构：** Go 内核（Tool 自描述接口 + Pipeline 6 步管道 + Resource 泛化 Gate + Sanitizer 脱敏 + EventBus + Scheduler/Account）跑在 Unix socket 上；Python 运行时（DeepSeek 客户端含自适应 rate limit + ReAct 循环）。脱敏是第一道防线，审计通过订阅 EventBus 事件产生。

**技术栈：** Go 1.22+、Python 3.11+、gRPC + protobuf、`github.com/bmatcuk/doublestar/v4`、`golang.org/x/time/rate`、`openai` Python SDK（DeepSeek 走 OpenAI 兼容 base_url）、`pytest`、Go `testing`。

**对应设计文档：** `docs/superpowers/specs/2026-06-24-agentos-mvp-design-v2.3.md`

---

## ⚠️ 重要说明（先读）

1. **不要提交代码到 git。** 按用户要求，所有实现代码只保留在本地。下面的"检查点"步骤是本地里程碑——**不要执行 `git commit`**。
2. **本机工具链现状（已探测确认）**：
   - Go 1.26.4 已装在 `E:\Go\bin\go.exe`，**但不在 PATH**——任务 1 必须先把它加到 PATH
   - miniconda 已装在 `E:\miniconda3`，在 PATH
   - **protoc 未装**——任务 1 要装
   - **protoc-gen-go 未装**——任务 1 要装
   - Python 用 conda 环境管理，**不要用系统 python**——任务 1 建一个专用环境
3. **工具名用下划线**（`fs_read`，不是 `fs.read`）。OpenAI/DeepSeek 函数名正则拒绝点号——真实坑。
4. **Unix domain socket 在 Windows 10 1803+ 可用**（本机 build 26100）。
5. **架构核心**：Kernel 不认识任何具体工具，只驱动 Pipeline。加工具 = 写 Tool 实现 + 注册，Kernel 核心零改。
6. **脱敏是第一道防线**，在 Pipeline 第 5 步统一执行，独立于工具。
7. **审计通过订阅 EventBus 事件产生**，不再散落调用 `ledger.Append()`。
8. **Shell 注意**：本计划命令在 cmd.exe 或 powershell 下执行。bash（如 git-bash）可能因 PATH 差异失败，优先用 cmd/powershell。

---

## 文件结构

```
AgentOS/
├── go.mod
├── kernel/
│   ├── cmd/agentos/
│   │   └── main.go                         # CLI: serve / audit show
│   └── internal/
│       ├── pb/                             # 生成的 protobuf (Go)
│       ├── resource/                       # Resource 抽象
│       │   └── resource.go
│       ├── policy/                         # Policy + Gate（泛化匹配）
│       │   ├── policy.go
│       │   ├── gate.go
│       │   └── *_test.go
│       ├── sanitize/                       # 脱敏层（核心壁垒）
│       │   ├── sanitizer.go
│       │   └── sanitizer_test.go
│       ├── audit/                          # hash 链账本 + 订阅者
│       │   ├── ledger.go
│       │   ├── ledger_test.go
│       │   └── subscriber.go
│       ├── eventbus/                       # in-process EventBus
│       │   ├── bus.go
│       │   └── bus_test.go
│       ├── sandbox/                        # Sandbox 接口 + path 校验
│       │   ├── sandbox.go
│       │   ├── inprocess.go
│       │   ├── fs.go                       # Resolve
│       │   └── fs_test.go
│       ├── tools/                          # Tool 接口 + fs 工具实现
│       │   ├── tool.go                     # Tool 接口 + Registry
│       │   ├── fs_tools.go
│       │   └── fs_tools_test.go
│       ├── session/                        # Session + Account + Snapshot
│       │   ├── account.go
│       │   ├── account_test.go
│       │   └── session.go
│       ├── scheduler/                      # 并发信号量
│       │   ├── scheduler.go
│       │   └── scheduler_test.go
│       ├── auth/                           # Authenticator 接口 + Policy 白名单
│       │   ├── auth.go
│       │   └── policy_guard.go
│       ├── pipeline/                       # 6 步统一管道
│       │   ├── pipeline.go
│       │   └── pipeline_test.go
│       └── server/                         # gRPC 服务端
│           └── server.go
├── proto/
│   └── agentos.proto
├── runtime/
│   ├── pyproject.toml
│   ├── agentos_runtime/
│   │   ├── __init__.py
│   │   ├── pb/                             # 生成 protobuf (Python)
│   │   ├── kernel_client.py
│   │   ├── rate_limit.py                   # 自适应 rate limiter
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   └── deepseek.py
│   │   ├── tools.py                        # 工具 schema（从 Go Schema 同步）
│   │   ├── loop.py
│   │   └── cli.py
│   └── tests/
│       ├── test_kernel_client.py
│       ├── test_loop.py
│       └── test_rate_limit.py
├── examples/
│   ├── policies/
│   │   └── data_analyst.yaml
│   ├── sanitization/
│   │   └── pii_rules.yaml
│   └── workspace/
│       ├── sales.csv
│       └── out/
├── policies/                               # 受信 Policy 目录（Kernel 认证白名单）
│   └── .gitkeep
└── docs/superpowers/
    └── ...
```

**拆分理由：** 每个包单一职责、可独立 TDD。`resource/policy/sanitize/audit/eventbus/scheduler/account` 是纯逻辑（无网络）。`sandbox/tools` 依赖 sandbox。`pipeline` 是核心集成点，用假 Tool/假 EventBus 测。`server` 在 gRPC 后接 Pipeline。

---

# 阶段 0 — 环境与骨架

## 任务 1：配置并验证工具链

**文件：** 无（仅环境）

**本机现状（已探测）**：Go 1.26.4 装在 `E:\Go\bin\`（不在 PATH）、miniconda 装在 `E:\miniconda3`（在 PATH）、protoc 未装。

- [ ] **步骤 1：把 Go 加到 PATH（永久）**

用 powershell 把 Go 永久加到用户 PATH（这样后续所有终端都能用）：

```
powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';E:\Go\bin', 'User')"
```

然后**关闭并重开终端**（PATH 变更只对新进程生效）。验证：

```
go version
```
预期：`go version go1.26.4 windows/amd64`

如果仍找不到，临时方案（仅当前会话）：
- cmd：`set PATH=E:\Go\bin;%PATH%`
- powershell：`$env:Path = 'E:\Go\bin;' + $env:Path`

- [ ] **步骤 2：建 conda 环境（agentos，Python 3.11+）**

不要用 base 环境，建一个专用环境隔离依赖：

```
conda create -n agentos python=3.11 -y
conda activate agentos
```

验证：
```
python --version
```
预期：`Python 3.11.x`

> **重要**：后续所有 Python 相关任务（任务 18-23、25）执行前都必须先 `conda activate agentos`。subagent 执行时要在命令前带 `conda activate agentos &&` 或在已激活的 shell 里跑。

- [ ] **步骤 3：安装 protoc**

从 https://github.com/protocolbuffers/protobuf/releases 下载 `protoc-<版本>-win64.zip`。解压后把 `bin\protoc.exe` 放到一个固定位置（建议 `E:\protoc\bin\protoc.exe`），并把这个目录也加到 PATH：

```
powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';E:\protoc\bin', 'User')"
```

重开终端，验证：
```
protoc --version
```
预期：`libprotoc 27.x`（或任意较新版本）。

- [ ] **步骤 4：安装 Go gRPC 插件**

```
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

这两个装到 `$GOPATH/bin`（默认 `%USERPROFILE%\go\bin`）。把它加到 PATH：

```
powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:USERPROFILE + '\go\bin', 'User')"
```

重开终端，验证：
```
protoc-gen-go --version
```
预期：`protoc-gen-go v1.x.x`。

- [ ] **步骤 5：在 conda 环境里装 Python 依赖**

```
conda activate agentos
pip install grpcio grpcio-tools openai pytest
```

验证：
```
python -c "import grpc, openai, pytest; print('ok')"
```
预期：`ok`

- [ ] **步骤 6：设置 DeepSeek API key（用户手动）**

在运行运行时的 shell 里设置（每次开新终端都要设，或加到用户环境变量永久生效）：

```
set DEEPSEEK_API_KEY=sk-xxxxxxxx        (cmd)
$env:DEEPSEEK_API_KEY="sk-xxxxxxxx"     (powershell)
```

永久设置：
```
powershell -Command "[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxxxxxxx', 'User')"
```

不要在仓库任何地方硬编码 key。

- [ ] **步骤 7：检查点** —— `go version`、`protoc --version`、`protoc-gen-go --version`、`conda activate agentos && python -c "import grpc,openai,pytest"` 全部成功。

不要在仓库任何地方硬编码 key。

---

## 任务 2：创建项目骨架 + go module

**文件：**
- 创建：`go.mod` + 目录树

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
mkdir kernel\internal\resource
mkdir kernel\internal\policy
mkdir kernel\internal\sanitize
mkdir kernel\internal\audit
mkdir kernel\internal\eventbus
mkdir kernel\internal\sandbox
mkdir kernel\internal\tools
mkdir kernel\internal\session
mkdir kernel\internal\scheduler
mkdir kernel\internal\auth
mkdir kernel\internal\pipeline
mkdir kernel\internal\server
mkdir proto
mkdir runtime\agentos_runtime\pb
mkdir runtime\agentos_runtime\llm
mkdir runtime\tests
mkdir examples\policies
mkdir examples\sanitization
mkdir examples\workspace\out
mkdir policies
```

- [ ] **步骤 3：检查点** —— 目录树存在（不提交）。

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
  string sanitization_path = 2;
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

生成 `proto/agentos.pb.go` 和 `proto/agentos_grpc.pb.go`，移入 pb 包：

```
move proto\agentos.pb.go kernel\internal\pb\agentos.pb.go
move proto\agentos_grpc.pb.go kernel\internal\pb\agentos_grpc.pb.go
```

确认 `kernel/internal/pb/agentos.pb.go` 顶部是 `package pb`。如果是 `package agentos`，两个文件顶部都改成 `package pb`。

- [ ] **步骤 3：生成 Python 代码**

```
cd runtime
python -m grpc_tools.protoc -I../proto ^
  --python_out=agentos_runtime/pb ^
  --grpc_python_out=agentos_runtime/pb ^
  ../proto/agentos.proto
```

创建 `runtime/agentos_runtime/pb/__init__.py`（空）。在生成的 `agentos_pb2_grpc.py` 里，把 `import agentos_pb2 as agentos__pb2` 改成相对导入：

```python
from . import agentos_pb2 as agentos__pb2
```

- [ ] **步骤 4：验证两侧编译**

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

- [ ] **步骤 5：检查点** —— proto 契约两侧编译通过。

---

# 阶段 1 — 内核基础（纯逻辑，TDD）

## 任务 4：Resource 抽象 + Policy 加载

**文件：**
- 创建：`kernel/internal/resource/resource.go`
- 创建：`kernel/internal/policy/policy.go`
- 创建：`kernel/internal/policy/policy_test.go`
- 创建：`examples/policies/data_analyst.yaml`

**背景：** Resource 是权限判定的泛化对象（`{Type, ID}`），不再特化于路径。Policy 含权限规则列表 + 脱敏规则引用 + 资源限额。

- [ ] **步骤 1：写 Resource 类型**

`kernel/internal/resource/resource.go`:
```go
package resource

// Resource 是权限判定的泛化对象。
// Type 决定匹配哪类规则（path/db_table/http_url...），ID 是具体标识。
type Resource struct {
	Type string
	ID   string
}
```

- [ ] **步骤 2：写失败测试**

`kernel/internal/policy/policy_test.go`:
```go
package policy

import "testing"

func TestLoadPolicy(t *testing.T) {
	p, err := LoadFromFile("../../examples/policies/data_analyst.yaml")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if p.AgentRole != "data_analyst" {
		t.Errorf("role = %q, want data_analyst", p.AgentRole)
	}
	if len(p.Permissions) == 0 {
		t.Fatal("permissions empty")
	}
	if p.Permissions[0].ResourceType != "path" {
		t.Errorf("first rule resource_type = %q, want path", p.Permissions[0].ResourceType)
	}
	if p.MaxSteps != 20 {
		t.Errorf("max_steps = %d, want 20", p.MaxSteps)
	}
	if p.SanitizationPath == "" {
		t.Error("sanitization_path empty")
	}
}
```

- [ ] **步骤 3：运行测试验证它失败**

```
go test ./kernel/internal/policy/
```
预期：FAIL —— `LoadFromFile` 未定义。

- [ ] **步骤 4：写策略 YAML**

`examples/policies/data_analyst.yaml`:
```yaml
agent_role: data_analyst
permissions:
  - resource_type: path
    pattern: "examples/workspace/**"
    actions: [fs_read, fs_list]
  - resource_type: path
    pattern: "examples/workspace/out/**"
    actions: [fs_write]
sanitization_path: "examples/sanitization/pii_rules.yaml"
max_steps: 20
max_tokens: 50000
```

- [ ] **步骤 5：写实现**

添加 yaml：
```
go get gopkg.in/yaml.v3
```

`kernel/internal/policy/policy.go`:
```go
package policy

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Rule 是一条权限规则：某资源类型 + glob 模式 + 允许的动作集合。
type Rule struct {
	ResourceType string   `yaml:"resource_type"`
	Pattern      string   `yaml:"pattern"`
	Actions      []string `yaml:"actions"`
}

// Policy 是授予一个 agent 会话的完整策略。
type Policy struct {
	AgentRole       string `yaml:"agent_role"`
	Permissions     []Rule `yaml:"permissions"`
	SanitizationPath string `yaml:"sanitization_path"`
	MaxSteps        int    `yaml:"max_steps"`
	MaxTokens       int    `yaml:"max_tokens"`
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
		p.MaxSteps = 20
	}
	return &p, nil
}
```

- [ ] **步骤 6：运行测试验证它通过**

```
go test ./kernel/internal/policy/
```
预期：PASS。

- [ ] **步骤 7：检查点**

---

## 任务 5：Gate 泛化（Resource 匹配）

**文件：**
- 创建：`kernel/internal/policy/gate.go`
- 创建：`kernel/internal/policy/gate_test.go`

**背景：** Gate 接收 `(action, Resource)`，按规则匹配。它**不认识任何工具名**，只做通用的 (action, resource.Type, resource.ID) 三元匹配。

- [ ] **步骤 1：写失败测试**

`kernel/internal/policy/gate_test.go`:
```go
package policy

import (
	"agentos/kernel/internal/resource"
	"testing"
)

func samplePolicy() *Policy {
	return &Policy{
		Permissions: []Rule{
			{ResourceType: "path", Pattern: "examples/workspace/**", Actions: []string{"fs_read", "fs_list"}},
			{ResourceType: "path", Pattern: "examples/workspace/out/**", Actions: []string{"fs_write"}},
		},
	}
}

func TestGateAllowsReadInRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if !g.Allowed("fs_read", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Error("expected fs_read allowed")
	}
}

func TestGateDeniesReadOutsideRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "/etc/passwd"}) {
		t.Error("expected /etc/passwd denied")
	}
}

func TestGateDeniesTraversalEscape(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "examples/workspace/../../../etc/passwd"}) {
		t.Error("expected traversal denied")
	}
}

func TestGateEnforcesWriteRoot(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Error("write outside out/ must be denied")
	}
	if !g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/out/result.txt"}) {
		t.Error("write inside out/ must be allowed")
	}
}

func TestGateDeniesUnknownResourceType(t *testing.T) {
	g := NewGate(samplePolicy())
	// 没有任何 db_table 规则，db_query 必须被拒
	if g.Allowed("db_query", resource.Resource{Type: "db_table", ID: "orders"}) {
		t.Error("unknown resource type must be denied")
	}
}

func TestGateDeniesUnknownAction(t *testing.T) {
	g := NewGate(samplePolicy())
	if g.Allowed("shell_exec", resource.Resource{Type: "path", ID: "examples/workspace/x"}) {
		t.Error("unknown action must be denied")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/policy/
```
预期：FAIL —— `NewGate`、`Allowed` 未定义。

- [ ] **步骤 3：实现 Gate**

添加 doublestar：
```
go get github.com/bmatcuk/doublestar/v4
```

`kernel/internal/policy/gate.go`:
```go
package policy

import (
	"path/filepath"
	"strings"

	"agentos/kernel/internal/resource"

	"github.com/bmatcuk/doublestar/v4"
)

// Gate 按 Policy 的规则匹配 (action, resource)。
// 它不认识任何工具名，只做通用的三元匹配。
type Gate struct {
	rules []Rule
}

func NewGate(p *Policy) *Gate {
	return &Gate{rules: p.Permissions}
}

// Allowed 报告 action 是否允许对 res 执行。
func (g *Gate) Allowed(action string, res resource.Resource) bool {
	for _, rule := range g.rules {
		if rule.ResourceType != res.Type {
			continue
		}
		if !containsAction(rule.Actions, action) {
			continue
		}
		if matchID(rule.Pattern, rule.ResourceType, res.ID) {
			return true
		}
	}
	return false
}

func containsAction(actions []string, action string) bool {
	for _, a := range actions {
		if a == action {
			return true
		}
	}
	return false
}

// matchID 按资源类型决定匹配方式。
// path 类型：glob 匹配 + 拒绝穿越/绝对路径。
// 其它类型：精确匹配 ID（未来可扩展）。
func matchID(pattern, resourceType, id string) bool {
	if resourceType == "path" {
		return matchPath(pattern, id)
	}
	return pattern == id
}

func matchPath(pattern, path string) bool {
	clean := filepath.Clean(path)
	if filepath.IsAbs(clean) {
		return false
	}
	for _, seg := range strings.Split(filepath.ToSlash(clean), "/") {
		if seg == ".." {
			return false
		}
	}
	ok, err := doublestar.Match(pattern, clean)
	return err == nil && ok
}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/policy/
```
预期：PASS（全部 gate + policy 测试）。

- [ ] **步骤 5：检查点**

---

## 任务 6：Sanitizer 脱敏层（核心壁垒）

**文件：**
- 创建：`kernel/internal/sanitize/sanitizer.go`
- 创建：`kernel/internal/sanitize/sanitizer_test.go`
- 创建：`examples/sanitization/pii_rules.yaml`

**背景：** 数据分析场景的第一道防线。按字段名匹配规则，应用 mask/hash/redact 三种策略。配置驱动，独立于工具。

- [ ] **步骤 1：写脱敏规则 YAML**

`examples/sanitization/pii_rules.yaml`:
```yaml
fields:
  - name: "id_card"
    strategy: mask
  - name: "phone"
    strategy: mask
    keep_prefix: 3
    keep_suffix: 4
  - name: "customer_id"
    strategy: hash
  - name: "remark"
    strategy: redact
```

- [ ] **步骤 2：写失败测试**

`kernel/internal/sanitize/sanitizer_test.go`:
```go
package sanitize

import (
	"testing"
)

func TestMaskFull(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "id_card", Strategy: "mask"}})
	out := r.Sanitize(map[string]any{"id_card": "110101199001011234"})
	if out["id_card"] != "***" {
		t.Errorf("got %v", out["id_card"])
	}
}

func TestMaskKeepPrefixSuffix(t *testing.T) {
	r := NewFromRules([]FieldRule{
		{Name: "phone", Strategy: "mask", KeepPrefix: 3, KeepSuffix: 4},
	})
	out := r.Sanitize(map[string]any{"phone": "13812341234"})
	if out["phone"] != "138****1234" {
		t.Errorf("got %v", out["phone"])
	}
}

func TestHashStable(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "customer_id", Strategy: "hash"}})
	out1 := r.Sanitize(map[string]any{"customer_id": "C001"})
	out2 := r.Sanitize(map[string]any{"customer_id": "C001"})
	if out1["customer_id"] != out2["customer_id"] {
		t.Error("hash must be stable")
	}
	if out1["customer_id"] == "C001" {
		t.Error("hash must not be original")
	}
}

func TestRedact(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "remark", Strategy: "redact"}})
	out := r.Sanitize(map[string]any{"remark": "secret info"})
	if _, ok := out["remark"]; ok {
		t.Error("redact must remove field")
	}
}

func TestUnmatchedFieldUntouched(t *testing.T) {
	r := NewFromRules([]FieldRule{{Name: "phone", Strategy: "mask"}})
	out := r.Sanitize(map[string]any{"amount": 100})
	if out["amount"] != 100 {
		t.Errorf("amount should be untouched, got %v", out["amount"])
	}
}

func TestLoadFromFile(t *testing.T) {
	r, err := LoadFromFile("../../examples/sanitization/pii_rules.yaml")
	if err != nil {
		t.Fatal(err)
	}
	out := r.Sanitize(map[string]any{"id_card": "x", "customer_id": "y"})
	if out["id_card"] != "***" {
		t.Errorf("id_card not masked: %v", out["id_card"])
	}
	if out["customer_id"] == "y" {
		t.Error("customer_id not hashed")
	}
}
```

- [ ] **步骤 3：运行测试验证它们失败**

```
go test ./kernel/internal/sanitize/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 4：实现 Sanitizer**

`kernel/internal/sanitize/sanitizer.go`:
```go
package sanitize

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

// FieldRule 是单字段的脱敏规则。
type FieldRule struct {
	Name       string `yaml:"name"`
	Strategy   string `yaml:"strategy"` // mask | hash | redact
	KeepPrefix int    `yaml:"keep_prefix"`
	KeepSuffix int    `yaml:"keep_suffix"`
}

type rulesFile struct {
	Fields []FieldRule `yaml:"fields"`
}

// Sanitizer 按字段名应用脱敏规则。线程安全（规则只读）。
type Sanitizer struct {
	rules map[string]FieldRule
}

func NewFromRules(rules []FieldRule) *Sanitizer {
	m := make(map[string]FieldRule, len(rules))
	for _, r := range rules {
		m[r.Name] = r
	}
	return &Sanitizer{rules: m}
}

func LoadFromFile(path string) (*Sanitizer, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var rf rulesFile
	if err := yaml.Unmarshal(data, &rf); err != nil {
		return nil, err
	}
	return NewFromRules(rf.Fields), nil
}

// Sanitize 对 data 中匹配规则的字段应用脱敏，返回新的 map（不改原 map）。
func (s *Sanitizer) Sanitize(data map[string]any) map[string]any {
	out := make(map[string]any, len(data))
	for k, v := range data {
		rule, ok := s.rules[k]
		if !ok {
			out[k] = v
			continue
		}
		out[k] = s.apply(rule, v)
	}
	return out
}

func (s *Sanitizer) apply(rule FieldRule, v any) any {
	str, ok := v.(string)
	if !ok {
		// 非字符串字段：hash 策略转字符串后哈希；其它策略原样返回。
		if rule.Strategy == "hash" {
			return hashValue(v)
		}
		return v
	}
	switch rule.Strategy {
	case "mask":
		return maskString(str, rule.KeepPrefix, rule.KeepSuffix)
	case "hash":
		return hashString(str)
	case "redact":
		return nil // 序列化时会被 JSON omit 掉——但为安全，调用方应检查
	default:
		return str
	}
}

func maskString(s string, keepPrefix, keepSuffix int) string {
	if keepPrefix == 0 && keepSuffix == 0 {
		return "***"
	}
	if len(s) <= keepPrefix+keepSuffix {
		return "***"
	}
	return s[:keepPrefix] + strings.Repeat("*", len(s)-keepPrefix-keepSuffix) + s[len(s)-keepSuffix:]
}

func hashString(s string) string {
	h := sha256.Sum256([]byte(s))
	return "h_" + hex.EncodeToString(h[:])[:16]
}

func hashValue(v any) string {
	return hashString(strings.TrimSpace(""))
}
```

> **注意（redact 处理）**：上面 redact 返回 `nil`，`Sanitize` 会把 `nil` 放进 map。JSON 序列化时 `nil` 会变成 `"remark":null` 而不是省略。如果希望完全移除字段（更安全），改 `apply`：redact 时返回一个哨兵，`Sanitize` 检测哨兵后不写入 map。下面给出这个更安全的版本——**用这个替换上面的 Sanitize/apply**：

```go
type omitField struct{}

var omit = omitField{}

func (s *Sanitizer) Sanitize(data map[string]any) map[string]any {
	out := make(map[string]any, len(data))
	for k, v := range data {
		rule, ok := s.rules[k]
		if !ok {
			out[k] = v
			continue
		}
		applied := s.apply(rule, v)
		if _, isOmit := applied.(omitField); isOmit {
			continue // redact：完全移除字段
		}
		out[k] = applied
	}
	return out
}
```
并把 `apply` 里 `case "redact": return omit`（替换 `return nil`）。

- [ ] **步骤 5：运行测试验证它们通过**

```
go test ./kernel/internal/sanitize/
```
预期：PASS（6 个测试）。

- [ ] **步骤 6：检查点**

---

## 任务 7：Audit Ledger（hash 链）

**文件：**
- 创建：`kernel/internal/audit/ledger.go`
- 创建：`kernel/internal/audit/ledger_test.go`

**背景：** append-only，每行一个 JSON 对象，hash 链防篡改。审计通过订阅 EventBus 写入（任务 14），ledger 本身只管读写。

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

	raw, _ := os.ReadFile(path)
	lines := bytes.Split(bytes.TrimSpace(raw), []byte("\n"))
	var e Entry
	_ = json.Unmarshal(lines[0], &e)
	e.Outcome = "denied"
	b, _ := json.Marshal(e)
	lines[0] = b
	_ = os.WriteFile(path, bytes.Join(lines, []byte("\n")), 0644)

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

- [ ] **步骤 3：实现 Ledger**

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

// Entry 是一条被审计的事件记录。
type Entry struct {
	SessionID  string `json:"session_id"`
	Timestamp  int64  `json:"timestamp_nano"`
	Tool       string `json:"tool"`
	ParamsJSON string `json:"params_json"`
	Outcome    string `json:"outcome"` // "allowed" | "denied" | "error" | "session_started" | "session_ended" | "quota_exceeded"
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

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/audit/
```
预期：PASS（3 个测试）。

- [ ] **步骤 5：检查点**

---

## 任务 8：EventBus（in-process 同步分发）

**文件：**
- 创建：`kernel/internal/eventbus/bus.go`
- 创建：`kernel/internal/eventbus/bus_test.go`

**背景：** Kernel 内部事件骨架。同步分发（保证顺序可预测），fire-and-forget（订阅者 panic 不炸主流程）。审计是它的第一个订阅者。

- [ ] **步骤 1：写失败测试**

`kernel/internal/eventbus/bus_test.go`:
```go
package eventbus

import (
	"sync"
	"testing"
)

func TestPublishDeliversToSubscriber(t *testing.T) {
	b := NewInProcess()
	var got []Event
	b.Subscribe(func(e Event) { got = append(got, e) })
	b.Publish(Event{Type: "tool.called", SessionID: "s1"})
	if len(got) != 1 || got[0].Type != "tool.called" {
		t.Fatalf("got %v", got)
	}
}

func TestMultipleSubscribers(t *testing.T) {
	b := NewInProcess()
	var n int
	var mu sync.Mutex
	b.Subscribe(func(e Event) { mu.Lock(); n++; mu.Unlock() })
	b.Subscribe(func(e Event) { mu.Lock(); n++; mu.Unlock() })
	b.Publish(Event{Type: "x"})
	if n != 2 {
		t.Errorf("both subscribers should fire, got %d", n)
	}
}

func TestSubscriberPanicDoesNotBreakMain(t *testing.T) {
	b := NewInProcess()
	var reached bool
	b.Subscribe(func(e Event) { panic("boom") })
	b.Subscribe(func(e Event) { reached = true })
	b.Publish(Event{Type: "x"})
	if !reached {
		t.Error("second subscriber should still run after first panicked")
	}
}

func TestEventHasTimestamp(t *testing.T) {
	b := NewInProcess()
	var ts int64
	b.Subscribe(func(e Event) { ts = e.Timestamp })
	b.Publish(Event{Type: "x"})
	if ts == 0 {
		t.Error("timestamp should be set")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/eventbus/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 3：实现 EventBus**

`kernel/internal/eventbus/bus.go`:
```go
package eventbus

import (
	"sync"
	"time"
)

// Event 是 Kernel 内一切值得关注的事件。
type Event struct {
	Type      string         // tool.called | tool.denied | tool.errored | session.started | session.ended | quota.exceeded
	SessionID string
	Tool      string
	Params    map[string]any
	Result    map[string]any
	Identity  string // 启动 agent 的身份（来自 Authenticator）
	Timestamp int64
}

// Bus 是事件总线接口。
type Bus interface {
	Publish(event Event)
	Subscribe(handler func(Event))
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

func (b *InProcess) Subscribe(h func(Event)) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.handlers = append(b.handlers, h)
}

func (b *InProcess) Publish(e Event) {
	e.Timestamp = time.Now().UnixNano()
	b.mu.Lock()
	handlers := append([]func(Event){}, b.handlers...) // 快照，避免回调里改订阅列表的竞态
	b.mu.Unlock()
	for _, h := range handlers {
		func() {
			defer func() { _ = recover() }()
			h(e)
		}()
	}
}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/eventbus/
```
预期：PASS（4 个测试）。

- [ ] **步骤 5：检查点**

---

# 阶段 2 — 内核服务（Sandbox / Tool / Pipeline）

## 任务 9：Sandbox 接口 + InProcess + path 校验

**文件：**
- 创建：`kernel/internal/sandbox/sandbox.go`
- 创建：`kernel/internal/sandbox/inprocess.go`
- 创建：`kernel/internal/sandbox/fs.go`
- 创建：`kernel/internal/sandbox/fs_test.go`

**背景：** Sandbox 是抽象接口（为未来代码执行沙箱预留），MVP 只有 InProcessSandbox（不跑任意代码）。`Resolve` 做 path 型工具的路径强校验（防穿越、防符号链接逃逸）。

- [ ] **步骤 1：写 Sandbox 接口 + InProcess 实现**

`kernel/internal/sandbox/sandbox.go`:
```go
package sandbox

// Sandbox 是执行环境抽象。MVP 只有 InProcess（不跑任意代码）。
// 未来加 WasmSandbox / ContainerSandbox 支持代码执行。
type Sandbox interface {
	// Type 返回沙箱类型标识（"inprocess" | "wasm" | "container"）。
	Type() string
}
```

`kernel/internal/sandbox/inprocess.go`:
```go
package sandbox

// InProcess 是 MVP 唯一的 Sandbox 实现：工具在 Kernel 进程内执行，不跑任意代码。
// path 型工具的路径安全由 Resolve 保证。
type InProcess struct{}

func (InProcess) Type() string { return "inprocess" }
```

- [ ] **步骤 2：写失败测试**

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
	target := t.TempDir()
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

- [ ] **步骤 3：运行测试验证它们失败**

```
go test ./kernel/internal/sandbox/
```
预期：FAIL —— `Resolve` 未定义。

- [ ] **步骤 4：实现 Resolve**

`kernel/internal/sandbox/fs.go`:
```go
package sandbox

import (
	"fmt"
	"os"
	"path/filepath"
)

// Resolve 把请求路径转成安全的绝对路径。
// 拒绝：清洗后任何 ".." 段；真实落点逃出所在树的符号链接。
func Resolve(requested string) (string, error) {
	clean := filepath.Clean(requested)
	abs, err := filepath.Abs(clean)
	if err != nil {
		return "", err
	}
	for _, seg := range splitSegments(clean) {
		if seg == ".." {
			return "", fmt.Errorf("path traversal rejected: %s", requested)
		}
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		if os.IsNotExist(err) {
			parentReal, perr := filepath.EvalSymlinks(filepath.Dir(abs))
			if perr != nil {
				return "", fmt.Errorf("cannot resolve parent: %w", perr)
			}
			return filepath.Join(parentReal, filepath.Base(abs)), nil
		}
		return "", err
	}
	if !isUnder(real, filepath.Dir(abs)) && real != abs {
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

- [ ] **步骤 5：运行测试验证它们通过**

```
go test ./kernel/internal/sandbox/
```
预期：PASS。Windows 符号链接测试可能 skip，可接受。

- [ ] **步骤 6：检查点**

---

## 任务 10：Tool 接口 + fs 工具（含原子写）

**文件：**
- 创建：`kernel/internal/tools/tool.go`
- 创建：`kernel/internal/tools/fs_tools.go`
- 创建：`kernel/internal/tools/fs_tools_test.go`

**背景：** Tool 是自描述接口——加工具零改 Kernel。fs_read/fs_write/fs_list 实现。fs_write 用原子写（.tmp → rename）防半成品文件。

- [ ] **步骤 1：写 Tool 接口 + Registry**

`kernel/internal/tools/tool.go`:
```go
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
// 加新工具 = 实现这个接口 + 注册，Kernel 核心零改。
type Tool interface {
	Name() string
	Schema() json.RawMessage                       // 给 LLM 的 function schema
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
```

- [ ] **步骤 2：写失败测试**

`kernel/internal/tools/fs_tools_test.go`:
```go
package tools

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentos/kernel/internal/resource"
)

func TestFSReadPermissionKey(t *testing.T) {
	r := FSReadTool{}.PermissionKey(map[string]any{"path": "a/b.csv"})
	if r.Type != "path" || r.ID != "a/b.csv" {
		t.Errorf("got %+v", r)
	}
}

func TestFSReadExecute(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "hello.txt")
	_ = os.WriteFile(path, []byte("hi"), 0644)

	res, err := FSReadTool{}.Execute(context.Background(), map[string]any{"path": path})
	if err != nil {
		t.Fatal(err)
	}
	if res.Data["content"] != "hi" {
		t.Errorf("content = %v", res.Data["content"])
	}
}

func TestFSWriteAtomicThenRead(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "sub", "out.txt")
	if _, err := FSWriteTool{}.Execute(context.Background(), map[string]any{"path": target, "content": "boom"}); err != nil {
		t.Fatal(err)
	}
	res, _ := FSReadTool{}.Execute(context.Background(), map[string]any{"path": target})
	if res.Data["content"] != "boom" {
		t.Errorf("got %v", res.Data["content"])
	}
	// 原子写不应残留 .tmp 文件
	if _, err := os.Stat(target + ".tmp"); !os.IsNotExist(err) {
		t.Error("residual .tmp file found")
	}
}

func TestFSListExecute(t *testing.T) {
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "a.txt"), []byte("x"), 0644)
	_ = os.WriteFile(filepath.Join(dir, "b.txt"), []byte("x"), 0644)
	res, err := FSListTool{}.Execute(context.Background(), map[string]any{"path": dir})
	if err != nil {
		t.Fatal(err)
	}
	names, _ := res.Data["entries"].([]string)
	if len(names) != 2 {
		t.Errorf("got %d entries", len(names))
	}
}

func TestRegistryDispatch(t *testing.T) {
	r := NewRegistry()
	r.Register(FSReadTool{})
	t_, ok := r.Get("fs_read")
	if !ok {
		t.Fatal("fs_read not registered")
	}
	if t_.Name() != "fs_read" {
		t.Errorf("name = %q", t_.Name())
	}
}

// 静态断言：fs 工具实现了 Tool 接口
var _ Tool = FSReadTool{}
var _ Tool = FSWriteTool{}
var _ Tool = FSListTool{}
```

- [ ] **步骤 3：运行测试验证它们失败**

```
go test ./kernel/internal/tools/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 4：实现 fs 工具**

`kernel/internal/tools/fs_tools.go`:
```go
package tools

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"

	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sandbox"
)

// FSReadTool 读文本文件。
type FSReadTool struct{}

func (FSReadTool) Name() string { return "fs_read" }

func (FSReadTool) Schema() json.RawMessage {
	return json.RawMessage(`{
		"name": "fs_read",
		"description": "Read a text file. Path is relative to the workspace root.",
		"parameters": {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}
	}`)
}

func (FSReadTool) PermissionKey(params map[string]any) resource.Resource {
	path, _ := params["path"].(string)
	return resource.Resource{Type: "path", ID: path}
}

func (FSReadTool) Execute(ctx context.Context, params map[string]any) (Result, error) {
	path, _ := params["path"].(string)
	safe, err := sandbox.Resolve(path)
	if err != nil {
		return Result{}, err
	}
	data, err := os.ReadFile(safe)
	if err != nil {
		return Result{}, err
	}
	return Result{Data: map[string]any{"content": string(data)}}, nil
}

// FSWriteTool 写文本文件，原子写（.tmp → rename）防半成品。
type FSWriteTool struct{}

func (FSWriteTool) Name() string { return "fs_write" }

func (FSWriteTool) Schema() json.RawMessage {
	return json.RawMessage(`{
		"name": "fs_write",
		"description": "Write text content to a file (creates parent dirs).",
		"parameters": {"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}
	}`)
}

func (FSWriteTool) PermissionKey(params map[string]any) resource.Resource {
	path, _ := params["path"].(string)
	return resource.Resource{Type: "path", ID: path}
}

func (FSWriteTool) Execute(ctx context.Context, params map[string]any) (Result, error) {
	path, _ := params["path"].(string)
	content, _ := params["content"].(string)
	safe, err := sandbox.Resolve(path)
	if err != nil {
		return Result{}, err
	}
	if err := os.MkdirAll(filepath.Dir(safe), 0755); err != nil {
		return Result{}, err
	}
	// 原子写：先写 .tmp，再 rename。崩溃时要么旧文件要么新文件，无半成品。
	tmp := safe + ".tmp"
	if err := os.WriteFile(tmp, []byte(content), 0644); err != nil {
		return Result{}, err
	}
	if err := os.Rename(tmp, safe); err != nil {
		_ = os.Remove(tmp)
		return Result{}, err
	}
	return Result{Data: map[string]any{"bytes_written": len(content)}}, nil
}

// FSListTool 列目录条目。
type FSListTool struct{}

func (FSListTool) Name() string { return "fs_list" }

func (FSListTool) Schema() json.RawMessage {
	return json.RawMessage(`{
		"name": "fs_list",
		"description": "List file names in a directory.",
		"parameters": {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}
	}`)
}

func (FSListTool) PermissionKey(params map[string]any) resource.Resource {
	path, _ := params["path"].(string)
	return resource.Resource{Type: "path", ID: path}
}

func (FSListTool) Execute(ctx context.Context, params map[string]any) (Result, error) {
	path, _ := params["path"].(string)
	safe, err := sandbox.Resolve(path)
	if err != nil {
		return Result{}, err
	}
	entries, err := os.ReadDir(safe)
	if err != nil {
		return Result{}, err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e.Name())
	}
	return Result{Data: map[string]any{"entries": names}}, nil
}
```

- [ ] **步骤 5：运行测试验证它们通过**

```
go test ./kernel/internal/tools/
```
预期：PASS（含原子写测试）。

- [ ] **步骤 6：检查点**

---

## 任务 11：Account + Session（含 Snapshot 接口）

**文件：**
- 创建：`kernel/internal/session/account.go`
- 创建：`kernel/internal/session/account_test.go`
- 创建：`kernel/internal/session/session.go`

**背景：** Account 管单个 agent 的资源预算（MaxSteps + MaxTokens），超限硬终止。Session 含 Policy/Gate/Account/Ledger，并预留 Snapshot 接口（为未来持久化）。

- [ ] **步骤 1：写 Account 失败测试**

`kernel/internal/session/account_test.go`:
```go
package session

import "testing"

func TestAccountCharge(t *testing.T) {
	a := NewAccount(ResourceQuota{MaxSteps: 3, MaxTokens: 100})
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 1: %v", err)
	}
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 2: %v", err)
	}
	// 第三次步数到 3，未超
	if err := a.Charge(Usage{Steps: 1, Tokens: 30}); err != nil {
		t.Fatalf("charge 3 should be ok: %v", err)
	}
	// 第四次步数超 3
	if err := a.Charge(Usage{Steps: 1, Tokens: 10}); err == nil {
		t.Error("expected quota exceeded for steps")
	}
}

func TestAccountTokenExceeded(t *testing.T) {
	a := NewAccount(ResourceQuota{MaxSteps: 100, MaxTokens: 50})
	if err := a.Charge(Usage{Tokens: 30}); err != nil {
		t.Fatal(err)
	}
	if err := a.Charge(Usage{Tokens: 30}); err == nil {
		t.Error("expected token exceeded")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/session/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 3：实现 Account**

`kernel/internal/session/account.go`:
```go
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
	Steps     int
	Tokens    int
}

// Account 累计资源消耗，超限拒绝。
type Account struct {
	mu   sync.Mutex
	quota ResourceQuota
	used  Usage
}

func NewAccount(q ResourceQuota) *Account {
	return &Account{quota: q}
}

// Charge 扣减资源。任一项超限返回 ErrQuotaExceeded。
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

func (a *Account) Used() Usage {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.used
}

var ErrQuotaExceeded = errors.New("quota exceeded")
```

- [ ] **步骤 4：运行 Account 测试验证它们通过**

```
go test ./kernel/internal/session/
```
预期：PASS（2 个测试）。

- [ ] **步骤 5：写 Session 结构**

`kernel/internal/session/session.go`:
```go
package session

import (
	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/sanitize"
)

// Session 是一个运行中 agent 的内核侧状态。
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
	// 占位实现：返回 session 元信息。真正持久化留阶段 2。
	return []byte(s.ID), nil
}
```

- [ ] **步骤 6：检查点**

---

## 任务 12：Scheduler（并发信号量）

**文件：**
- 创建：`kernel/internal/scheduler/scheduler.go`
- 创建：`kernel/internal/scheduler/scheduler_test.go`

**背景：** Scheduler 限制同时在跑的 agent 数（信号量），保证公平 FIFO。MVP 不做 rate limit（rate limit 在 Runtime 侧，见任务 19）。接口为优先级调度预留。

- [ ] **步骤 1：写失败测试**

`kernel/internal/scheduler/scheduler_test.go`:
```go
package scheduler

import (
	"context"
	"sync"
	"testing"
	"time"
)

func TestConcurrencyLimit(t *testing.T) {
	s := New(2) // 最多 2 个并发
	var active, max int
	var mu sync.Mutex

	run := func() {
		ctx := context.Background()
		release, err := s.Acquire(ctx)
		if err != nil {
			t.Fatalf("acquire: %v", err)
		}
		defer release()
		mu.Lock()
		active++
		if active > max {
			max = active
		}
		mu.Unlock()
		time.Sleep(20 * time.Millisecond)
		mu.Lock()
		active--
		mu.Unlock()
	}

	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); run() }()
	}
	wg.Wait()
	if max > 2 {
		t.Errorf("max concurrent = %d, want <= 2", max)
	}
}

func TestAcquireCancelledContext(t *testing.T) {
	s := New(1)
	release, _ := s.Acquire(context.Background())
	defer release()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if _, err := s.Acquire(ctx); err == nil {
		t.Error("expected timeout error when slot unavailable")
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/scheduler/
```
预期：FAIL —— `New`/`Acquire` 未定义。

- [ ] **步骤 3：实现 Scheduler**

`kernel/internal/scheduler/scheduler.go`:
```go
package scheduler

import "context"

// Scheduler 用信号量限制并发 agent 数。FIFO 公平（Go channel 本质 FIFO）。
type Scheduler struct {
	sem chan struct{}
}

func New(maxConcurrent int) *Scheduler {
	return &Scheduler{sem: make(chan struct{}, maxConcurrent)}
}

// Acquire 占一个并发槽。返回 release 函数释放槽。
// ctx 取消时返回 ctx.Err()。
func (s *Scheduler) Acquire(ctx context.Context) (release func(), err error) {
	select {
	case s.sem <- struct{}{}:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return func() { <-s.sem }, nil
}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/scheduler/
```
预期：PASS（2 个测试）。

- [ ] **步骤 5：检查点**

---

## 任务 13：Pipeline（6 步统一管道）

**文件：**
- 创建：`kernel/internal/pipeline/pipeline.go`
- 创建：`kernel/internal/pipeline/pipeline_test.go`

**背景：** Kernel 心脏。6 步固定管道，审计通过 EventBus 事件触发（不散落）。Account 在每步后扣减。

- [ ] **步骤 1：写失败测试（用假 Tool + 假 EventBus）**

`kernel/internal/pipeline/pipeline_test.go`:
```go
package pipeline

import (
	"context"
	"encoding/json"
	"testing"

	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sanitize"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

// fakeTool 是一个可控的测试工具。
type fakeTool struct {
	name   string
	result map[string]any
}

func (f fakeTool) Name() string { return f.name }
func (f fakeTool) Schema() json.RawMessage { return nil }
func (f fakeTool) PermissionKey(params map[string]any) resource.Resource {
	return resource.Resource{Type: "path", ID: params["path"].(string)}
}
func (f fakeTool) Execute(ctx context.Context, params map[string]any) (tools.Result, error) {
	return tools.Result{Data: f.result}, nil
}

func newTestSession(t *testing.T) *session.Session {
	p := &policy.Policy{
		Permissions: []policy.Rule{
			{ResourceType: "path", Pattern: "ws/**", Actions: []string{"fake"}},
		},
		MaxSteps:  20,
		MaxTokens: 100000,
	}
	return &session.Session{
		ID:        "s1",
		Policy:    p,
		Gate:      policy.NewGate(p),
		Sanitizer: sanitize.NewFromRules([]sanitize.FieldRule{{Name: "secret", Strategy: "mask"}}),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: p.MaxSteps, MaxTokens: p.MaxTokens}),
	}
}

func TestPipelineAllowedPath(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{"content": "data", "secret": "pii"}})
	pipe := New(reg, bus)

	sess := newTestSession(t)
	resp := pipe.Call(sess, "fake", map[string]any{"path": "ws/x.csv"})
	if !resp.Allowed {
		t.Fatal("expected allowed")
	}
	// 脱敏应在结果中生效
	if resp.Result["secret"] == "pii" {
		t.Error("secret should be sanitized")
	}
}

func TestPipelineDeniedPath(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t)
	resp := pipe.Call(sess, "fake", map[string]any{"path": "/etc/passwd"})
	if resp.Allowed {
		t.Error("expected denied")
	}
	if resp.Message == "" {
		t.Error("denied should have generic message")
	}
}

func TestPipelineUnknownTool(t *testing.T) {
	bus := eventbus.NewInProcess()
	pipe := New(tools.NewRegistry(), bus)
	sess := newTestSession(t)
	resp := pipe.Call(sess, "nonexistent", map[string]any{"path": "ws/x"})
	if resp.Allowed {
		t.Error("unknown tool should be denied")
	}
}

func TestPipelinePublishesEvents(t *testing.T) {
	bus := eventbus.NewInProcess()
	var events []eventbus.Event
	bus.Subscribe(func(e eventbus.Event) { events = append(events, e) })

	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	sess := newTestSession(t)
	pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})

	found := false
	for _, e := range events {
		if e.Type == "tool.called" {
			found = true
		}
	}
	if !found {
		t.Error("expected tool.called event")
	}
}

func TestPipelineQuotaExceededTerminates(t *testing.T) {
	bus := eventbus.NewInProcess()
	reg := tools.NewRegistry()
	reg.Register(fakeTool{name: "fake", result: map[string]any{}})
	pipe := New(reg, bus)

	// 故意把 quota 设成 0，第一次调用就超步数
	p := &policy.Policy{
		Permissions: []policy.Rule{{ResourceType: "path", Pattern: "ws/**", Actions: []string{"fake"}}},
		MaxSteps:    0, // 0 不限制，用 MaxTokens=0 也不限制。改用 1 步超限。
		MaxTokens:   100000,
	}
	p.MaxSteps = 1
	sess := &session.Session{
		ID:        "s2",
		Policy:    p,
		Gate:      policy.NewGate(p),
		Sanitizer: sanitize.NewFromRules(nil),
		Account:   session.NewAccount(session.ResourceQuota{MaxSteps: 1, MaxTokens: p.MaxTokens}),
	}
	// 第一次：步数到 1，未超（Charge 后 used=1, quota=1, 1>1 false）
	resp := pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})
	if !resp.Allowed {
		t.Fatal("first call should be allowed")
	}
	// 第二次：used 步数到 2 > 1，超限
	resp = pipe.Call(sess, "fake", map[string]any{"path": "ws/x"})
	if resp.Allowed {
		t.Error("second call should be quota exceeded")
	}
	if resp.Errored == false && resp.Allowed == false {
		// 拒绝形态：allowed=false。确认 message 非空
		if resp.Message == "" {
			t.Error("quota exceeded should have message")
		}
	}
}
```

- [ ] **步骤 2：运行测试验证它们失败**

```
go test ./kernel/internal/pipeline/
```
预期：FAIL —— 类型未定义。

- [ ] **步骤 3：实现 Pipeline**

`kernel/internal/pipeline/pipeline.go`:
```go
package pipeline

import (
	"context"

	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/resource"
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

// Call 执行一次工具调用，经过权限/执行/脱敏/审计。
func (p *Pipeline) Call(sess *session.Session, toolName string, params map[string]any) Response {
	ctx := context.Background()

	// 步骤 1：查找工具
	tool, ok := p.registry.Get(toolName)
	if !ok {
		p.bus.Publish(eventbus.Event{
			Type: "tool.denied", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Allowed: false, Message: "permission denied"}
	}

	// 步骤 2：提取权限资源
	res := tool.PermissionKey(params)

	// 步骤 3：权限检查
	if !sess.Gate.Allowed(toolName, res) {
		p.bus.Publish(eventbus.Event{
			Type: "tool.denied", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Allowed: false, Message: "permission denied"}
	}

	// 步骤 3.5：资源扣减（超限硬终止）
	if err := sess.Account.Charge(session.Usage{Steps: 1}); err != nil {
		p.bus.Publish(eventbus.Event{
			Type: "quota.exceeded", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Errored: true, Message: "quota exceeded"}
	}

	// 步骤 4：执行
	result, err := tool.Execute(ctx, params)
	if err != nil {
		p.bus.Publish(eventbus.Event{
			Type: "tool.errored", SessionID: sess.ID, Tool: toolName, Params: params,
		})
		return Response{Errored: true, Message: "tool error"}
	}

	// 步骤 5：脱敏
	if sess.Sanitizer != nil {
		result.Data = sess.Sanitizer.Sanitize(result.Data)
	}

	// 步骤 6：审计（通过事件触发，AuditSubscriber 订阅）
	p.bus.Publish(eventbus.Event{
		Type: "tool.called", SessionID: sess.ID, Tool: toolName,
		Params: params, Result: result.Data,
	})

	return Response{Allowed: true, Result: result.Data}
}

// 用于未来扩展：显式标注 resource 包被使用
var _ = resource.Resource{}
```

- [ ] **步骤 4：运行测试验证它们通过**

```
go test ./kernel/internal/pipeline/
```
预期：PASS（5 个测试）。

- [ ] **步骤 5：检查点**

---

## 任务 14：Audit Subscriber（订阅事件写 ledger）

**文件：**
- 创建：`kernel/internal/audit/subscriber.go`

**背景：** 审计逻辑集中到一处。订阅 `tool.*` 和 `session.*` 事件，写 hash 链 ledger。解决 v1 的"审计散落"问题。

- [ ] **步骤 1：实现 Subscriber**

`kernel/internal/audit/subscriber.go`:
```go
package audit

import (
	"encoding/json"

	"agentos/kernel/internal/eventbus"
)

// RegisterAuditSubscriber 让 ledger 订阅 bus 上的相关事件并写审计。
// 这是审计逻辑的唯一集中点。
func RegisterAuditSubscriber(ledger *Ledger, bus eventbus.Bus) {
	bus.Subscribe(func(e eventbus.Event) {
		outcome := outcomeFor(e.Type)
		if outcome == "" {
			return // 不审计的事件类型
		}
		paramsJSON, _ := json.Marshal(e.Params)
		resultJSON, _ := json.Marshal(e.Result)
		_ = ledger.Append(Entry{
			SessionID:  e.SessionID,
			Tool:       e.Tool,
			ParamsJSON: string(paramsJSON),
			Outcome:    outcome,
			ResultJSON: string(resultJSON),
		})
	})
}

func outcomeFor(eventType string) string {
	switch eventType {
	case "tool.called":
		return "allowed"
	case "tool.denied":
		return "denied"
	case "tool.errored":
		return "error"
	case "session.started":
		return "session_started"
	case "session.ended":
		return "session_ended"
	case "quota.exceeded":
		return "quota_exceeded"
	default:
		return ""
	}
}
```

- [ ] **步骤 2：检查点**（集成测试在任务 26 覆盖端到端审计写入）。

---

## 任务 15：Authenticator + Policy 白名单

**文件：**
- 创建：`kernel/internal/auth/auth.go`
- 创建：`kernel/internal/auth/policy_guard.go`

**背景：** MVP 两层防御——socket 权限 0600（任务 17 在 CLI 做）+ Policy 路径白名单。Authenticator 接口为未来 mTLS/API key 预留。

- [ ] **步骤 1：实现 Authenticator + Policy 白名单**

`kernel/internal/auth/auth.go`:
```go
package auth

import "context"

// Identity 是调用方身份。
type Identity struct {
	Tenant string // MVP 单租户 = "default"
	User   string // MVP = "local"
}

// Authenticator 验证调用方身份。MVP 用 LocalAuthenticator（不验证，返回固定身份）。
// 未来加 mTLS/API key 是新实现。
type Authenticator interface {
	Authenticate(ctx context.Context) (Identity, error)
}

// LocalAuthenticator 是 MVP 实现：不验证，返回固定 "local" 身份。
type LocalAuthenticator struct{}

func (LocalAuthenticator) Authenticate(ctx context.Context) (Identity, error) {
	return Identity{Tenant: "default", User: "local"}, nil
}
```

`kernel/internal/auth/policy_guard.go`:
```go
package auth

import (
	"path/filepath"
	"strings"
)

// IsTrustedPolicy 检查 Policy 路径是否在受信目录内。
// 防止恶意进程加载全权限 Policy 绕过所有限制。
func IsTrustedPolicy(policyPath, trustedDir string) bool {
	abs, err := filepath.Abs(policyPath)
	if err != nil {
		return false
	}
	trustedAbs, err := filepath.Abs(trustedDir)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(trustedAbs, abs)
	if err != nil {
		return false
	}
	// rel 不能以 ".." 开头（逃出受信目录）
	return !strings.HasPrefix(filepath.ToSlash(rel), "../") && rel != ".."
}
```

- [ ] **步骤 2：检查点**（Server 在任务 16 调用 IsTrustedPolicy）。

---

# 阶段 3 — gRPC 服务端 + CLI

## 任务 16：gRPC Server（StartSession + CallTool + 认证 + 事件）

**文件：**
- 创建：`kernel/internal/server/server.go`

**背景：** 把 Pipeline/Session/Scheduler/EventBus/Authenticator 接起来。StartSession 校验 Policy 白名单、加载策略、发 `session.started` 事件。CallTool 通过 Scheduler 占并发槽后调 Pipeline。

- [ ] **步骤 1：实现 Server**

`kernel/internal/server/server.go`:
```go
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"time"

	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/auth"
	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/pb"
	"agentos/kernel/internal/pipeline"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/sanitize"
	"agentos/kernel/internal/scheduler"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

const trustedPolicyDir = "./policies"

type Server struct {
	pb.UnimplementedKernelServer
	sessions   *session.Manager
	registry   *tools.Registry
	scheduler  *scheduler.Scheduler
	auth       auth.Authenticator
	auditDir   string
	nextID     int64
}

func New(auditDir string) *Server {
	reg := tools.NewRegistry()
	reg.Register(tools.FSReadTool{})
	reg.Register(tools.FSWriteTool{})
	reg.Register(tools.FSListTool{})
	return &Server{
		sessions:  session.NewManager(),
		registry:  reg,
		scheduler: scheduler.New(4), // MVP 并发上限 4
		auth:      auth.LocalAuthenticator{},
		auditDir:  auditDir,
	}
}

func (s *Server) StartSession(ctx context.Context, req *pb.StartSessionRequest) (*pb.StartSessionResponse, error) {
	// Policy 白名单校验：防加载恶意全权限 Policy
	if !auth.IsTrustedPolicy(req.PolicyPath, trustedPolicyDir) {
		// MVP 阶段为方便演示：允许 examples/ 下的 Policy。生产应严格限制。
		if !auth.IsTrustedPolicy(req.PolicyPath, "./examples/policies") {
			return nil, fmt.Errorf("untrusted policy path: %s", req.PolicyPath)
		}
	}

	pol, err := policy.LoadFromFile(req.PolicyPath)
	if err != nil {
		return nil, fmt.Errorf("load policy: %w", err)
	}
	san, err := sanitize.LoadFromFile(req.SanitizationPath)
	if err != nil {
		return nil, fmt.Errorf("load sanitization: %w", err)
	}

	id := s.newSessionID()
	ledger, err := audit.New(filepath.Join(s.auditDir, id+".log"))
	if err != nil {
		return nil, err
	}

	// EventBus + 审计订阅
	bus := eventbus.NewInProcess()
	audit.RegisterAuditSubscriber(ledger, bus)

	identity, _ := s.auth.Authenticate(ctx)

	sess := &session.Session{
		ID:        id,
		Identity:  identity.User,
		Policy:    pol,
		Gate:      policy.NewGate(pol),
		Sanitizer: san,
		Account:   session.NewAccount(session.ResourceQuota{
			MaxSteps:  pol.MaxSteps,
			MaxTokens: pol.MaxTokens,
		}),
		Ledger: ledger,
	}
	s.sessions.Add(sess)

	// Pipeline 绑定这个 session 专用的 bus（这样审计按 session 分文件）
	sess.Pipeline = pipeline.New(s.registry, bus)

	bus.Publish(eventbus.Event{
		Type: "session.started", SessionID: id, Identity: identity.User,
	})

	return &pb.StartSessionResponse{SessionId: id}, nil
}

func (s *Server) CallTool(ctx context.Context, req *pb.CallToolRequest) (*pb.CallToolResponse, error) {
	sess, ok := s.sessions.Get(req.SessionId)
	if !ok {
		return nil, fmt.Errorf("unknown session %s", req.SessionId)
	}

	release, err := s.scheduler.Acquire(ctx)
	if err != nil {
		return nil, fmt.Errorf("scheduler: %w", err)
	}
	defer release()

	var params map[string]any
	if req.ParamsJson != "" {
		if err := json.Unmarshal([]byte(req.ParamsJson), &params); err != nil {
			params = map[string]any{}
		}
	}

	resp := sess.Pipeline.Call(sess, req.Tool, params)

	resultJSON, _ := json.Marshal(resp.Result)
	return &pb.CallToolResponse{
		Allowed:    resp.Allowed,
		Errored:    resp.Errored,
		Message:    resp.Message,
		ResultJson: string(resultJSON),
	}, nil
}

func (s *Server) newSessionID() string {
	s.nextID++
	return fmt.Sprintf("sess-%d-%d", time.Now().Unix(), s.nextID)
}
```

> **注意**：上面用到了 `session.Manager` 和 `sess.Pipeline` 字段。需要补：
> 1. `kernel/internal/session/manager.go`（简单 map 管理，见下）
> 2. `Session` 结构加 `Pipeline *pipeline.Pipeline` 字段（任务 11 的 session.go 需更新）
>
> 这两个补丁在步骤 2、3 给出。

- [ ] **步骤 2：写 Session Manager**

创建 `kernel/internal/session/manager.go`:
```go
package session

import "sync"

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

- [ ] **步骤 3：给 Session 加 Pipeline 字段**

修改 `kernel/internal/session/session.go`，在 Session 结构里加 Pipeline 字段。因为 pipeline 依赖 session，会循环依赖，所以用接口断开。更新 `session.go`：

```go
package session

import (
	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/sanitize"
)

// PipelineCaller 是 Pipeline 的最小接口，避免 session ↔ pipeline 循环依赖。
type PipelineCaller interface {
	Call(sess *Session, toolName string, params map[string]any) PipelineResponse
}

// PipelineResponse 是 Pipeline 返回（与 pipeline.Response 同构，避免循环依赖）。
type PipelineResponse struct {
	Allowed bool
	Errored bool
	Message string
	Result  map[string]any
}

type Session struct {
	ID        string
	Identity  string
	Policy    *policy.Policy
	Gate      *policy.Gate
	Sanitizer *sanitize.Sanitizer
	Account   *Account
	Ledger    *audit.Ledger
	// Pipeline 不放这里——由 Server 持有 (sessionID → pipeline) 映射。
	// 见任务 16 步骤 4 的修正。
}

func (s *Session) Snapshot() ([]byte, error) {
	return []byte(s.ID), nil
}
```

> **重要修正**：上面分析发现把 `Pipeline` 放进 `Session` 会导致循环依赖（pipeline import session，session import pipeline）。**正确做法**：Server 持有 `map[sessionID]*pipeline.Pipeline`，Session 不持有 Pipeline。见步骤 4 的 Server 修正版。

- [ ] **步骤 4：修正 Server（Session 不持有 Pipeline，改由 Server 管理）**

把任务 16 步骤 1 的 Server 改成：Server 维护 `pipelines map[string]*pipeline.Pipeline`。重新写 `kernel/internal/server/server.go`（用这个完整版覆盖步骤 1）：

```go
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"sync"
	"time"

	"agentos/kernel/internal/audit"
	"agentos/kernel/internal/auth"
	"agentos/kernel/internal/eventbus"
	"agentos/kernel/internal/pb"
	"agentos/kernel/internal/pipeline"
	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/sanitize"
	"agentos/kernel/internal/scheduler"
	"agentos/kernel/internal/session"
	"agentos/kernel/internal/tools"
)

type Server struct {
	pb.UnimplementedKernelServer
	mu         sync.Mutex
	sessions   map[string]*session.Session
	pipelines  map[string]*pipeline.Pipeline
	registry   *tools.Registry
	scheduler  *scheduler.Scheduler
	auth       auth.Authenticator
	auditDir   string
	nextID     int64
}

func New(auditDir string) *Server {
	reg := tools.NewRegistry()
	reg.Register(tools.FSReadTool{})
	reg.Register(tools.FSWriteTool{})
	reg.Register(tools.FSListTool{})
	return &Server{
		sessions:  map[string]*session.Session{},
		pipelines: map[string]*pipeline.Pipeline{},
		registry:  reg,
		scheduler: scheduler.New(4),
		auth:      auth.LocalAuthenticator{},
		auditDir:  auditDir,
	}
}

func (s *Server) StartSession(ctx context.Context, req *pb.StartSessionRequest) (*pb.StartSessionResponse, error) {
	// Policy 白名单校验
	if !auth.IsTrustedPolicy(req.PolicyPath, "./examples/policies") &&
		!auth.IsTrustedPolicy(req.PolicyPath, "./policies") {
		return nil, fmt.Errorf("untrusted policy path: %s", req.PolicyPath)
	}

	pol, err := policy.LoadFromFile(req.PolicyPath)
	if err != nil {
		return nil, fmt.Errorf("load policy: %w", err)
	}
	san, err := sanitize.LoadFromFile(req.SanitizationPath)
	if err != nil {
		return nil, fmt.Errorf("load sanitization: %w", err)
	}

	s.mu.Lock()
	s.nextID++
	id := fmt.Sprintf("sess-%d-%d", time.Now().Unix(), s.nextID)
	s.mu.Unlock()

	ledger, err := audit.New(filepath.Join(s.auditDir, id+".log"))
	if err != nil {
		return nil, err
	}

	bus := eventbus.NewInProcess()
	audit.RegisterAuditSubscriber(ledger, bus)

	identity, _ := s.auth.Authenticate(ctx)

	sess := &session.Session{
		ID:        id,
		Identity:  identity.User,
		Policy:    pol,
		Gate:      policy.NewGate(pol),
		Sanitizer: san,
		Account:   session.NewAccount(session.ResourceQuota{
			MaxSteps:  pol.MaxSteps,
			MaxTokens: pol.MaxTokens,
		}),
		Ledger: ledger,
	}
	pipe := pipeline.New(s.registry, bus)

	s.mu.Lock()
	s.sessions[id] = sess
	s.pipelines[id] = pipe
	s.mu.Unlock()

	bus.Publish(eventbus.Event{
		Type: "session.started", SessionID: id, Identity: identity.User,
	})

	return &pb.StartSessionResponse{SessionId: id}, nil
}

func (s *Server) CallTool(ctx context.Context, req *pb.CallToolRequest) (*pb.CallToolResponse, error) {
	s.mu.Lock()
	sess, ok := s.sessions[req.SessionId]
	pipe := s.pipelines[req.SessionId]
	s.mu.Unlock()
	if !ok || pipe == nil {
		return nil, fmt.Errorf("unknown session %s", req.SessionId)
	}

	release, err := s.scheduler.Acquire(ctx)
	if err != nil {
		return nil, fmt.Errorf("scheduler: %w", err)
	}
	defer release()

	var params map[string]any
	if req.ParamsJson != "" {
		if err := json.Unmarshal([]byte(req.ParamsJson), &params); err != nil {
			params = map[string]any{}
		}
	}

	resp := pipe.Call(sess, req.Tool, params)
	resultJSON, _ := json.Marshal(resp.Result)

	return &pb.CallToolResponse{
		Allowed:    resp.Allowed,
		Errored:    resp.Errored,
		Message:    resp.Message,
		ResultJson: string(resultJSON),
	}, nil
}
```

> 同时删掉任务 11 步骤 5 里 Session 结构中的任何 Pipeline 字段引用（步骤 3 已移除）。并删除 `session/manager.go` 里 `Manager` 相关——Server 直接用 map。如果之前建了 manager.go，可保留但 Server 不用它。

- [ ] **步骤 5：验证编译**

```
go build ./kernel/...
```
预期：无错误。核对 proto 字段 Go 名（`SessionId`、`PolicyPath`、`SanitizationPath`、`ParamsJson`、`ResultJson`）与 `kernel/internal/pb/agentos.pb.go` 一致。

- [ ] **步骤 6：检查点**

---

## 任务 17：Kernel CLI（serve + audit show）

**文件：**
- 修改：`kernel/cmd/agentos/main.go`

**背景：** `agentos serve` 起 gRPC 服务（socket 0600），`agentos audit show` 读审计日志并校验 hash 链。

- [ ] **步骤 1：实现 CLI**

`kernel/cmd/agentos/main.go`:
```go
package main

import (
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
	os.MkdirAll("./policies", 0755)
	_ = os.Remove(*socket) // 清上次残留 socket

	lis, err := net.Listen("unix", *socket)
	if err != nil {
		fmt.Println("listen:", err)
		os.Exit(1)
	}
	// Kernel 认证第一层：socket 文件权限 0600，只有 owner 能连
	_ = os.Chmod(*socket, 0600)

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
		target = filepath.Join("./audit", target+".log")
	}

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
		fmt.Println("⚠️  HASH 链校验失败:", err)
	} else {
		fmt.Println("✓ hash 链校验通过")
	}
	for _, e := range entries {
		fmt.Printf("%s  %s  %s  [%s]\n", e.SessionID, e.Tool, e.Outcome, e.ParamsJSON)
	}
}
```

- [ ] **步骤 2：构建**

```
go build -o agentos.exe ./kernel/cmd/agentos
```
预期：产出 `agentos.exe`。

- [ ] **步骤 3：冒烟测试（手动）**

终端 1：
```
agentos.exe serve -socket ./agentos.sock -audit-dir ./audit
```
预期：`agentos kernel listening on ./agentos.sock`。

- [ ] **步骤 4：检查点** —— Kernel 是运行中的 gRPC 服务。

---

# 阶段 4 — Python Runtime

## 任务 18：运行时包 + pyproject

**文件：**
- 创建：`runtime/pyproject.toml`
- 创建：`runtime/agentos_runtime/__init__.py`

- [ ] **步骤 1：写 pyproject.toml**

`runtime/pyproject.toml`:
```toml
[project]
name = "agentos-runtime"
version = "0.2.0"
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
预期：安装 `agentos-run` 命令行脚本。

- [ ] **步骤 3：检查点**

---

## 任务 19：自适应 Rate Limiter（防撞 DeepSeek 限流）

**文件：**
- 创建：`runtime/agentos_runtime/rate_limit.py`
- 创建：`runtime/tests/test_rate_limit.py`

**背景：** 选项 Z——保守 RPS 初值 + 遇 429 指数退避 + 动态调低 RPS。在 Runtime 侧实现（429 是 DeepSeek HTTP 响应，只有发起方感知）。

- [ ] **步骤 1：写失败测试**

`runtime/tests/test_rate_limit.py`:
```python
import time
from agentos_runtime.rate_limit import AdaptiveRateLimiter


def test_initial_rps():
    r = AdaptiveRateLimiter(initial_rpm=60)
    assert r.current_rpm() == 60


def test_on429_halves_rpm():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 30
    r.on_429()
    assert r.current_rpm() == 15


def test_on429_does_not_go_below_min():
    r = AdaptiveRateLimiter(initial_rpm=8, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 5  # 4 被钳到 5


def test_on_success_restores_rpm():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 30
    r.on_success()
    assert r.current_rpm() == 60  # 恢复


def test_should_wait_after_429():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5, base_backoff_sec=2.0)
    r.on_429()
    # 立即调用 should_wait 应该要等
    wait = r.should_wait()
    assert wait > 0
```

- [ ] **步骤 2：运行测试验证它失败**

```
cd runtime
pytest tests/test_rate_limit.py -v
```
预期：FAIL —— 模块找不到。

- [ ] **步骤 3：实现 Rate Limiter**

`runtime/agentos_runtime/rate_limit.py`:
```python
import time


class AdaptiveRateLimiter:
    """自适应限流器：保守初值 + 遇 429 退避降速 + 成功恢复。

    选项 Z 实现：兼顾稳定（不撞墙）和适应（动态调整）。
    """

    def __init__(self, initial_rpm: int = 30, min_rpm: int = 5,
                 base_backoff_sec: float = 1.0, max_rpm: int | None = None):
        self._rpm = float(initial_rpm)
        self._min_rpm = float(min_rpm)
        self._max_rpm = float(max_rpm if max_rpm else initial_rpm)
        self._base_backoff = base_backoff_sec
        self._backoff_until = 0.0
        self._consecutive_429 = 0

    def current_rpm(self) -> int:
        return int(self._rpm)

    def on_429(self):
        """收到 429 时：降速一半 + 设置指数退避冷却。"""
        self._rpm = max(self._min_rpm, self._rpm * 0.5)
        self._consecutive_429 += 1
        backoff = self._base_backoff * (2 ** (self._consecutive_429 - 1))
        self._backoff_until = time.monotonic() + backoff

    def on_success(self):
        """成功时：恢复到初值，清退避。"""
        self._rpm = self._max_rpm
        self._consecutive_429 = 0
        self._backoff_until = 0.0

    def should_wait(self) -> float:
        """返回距下次可以发请求还需等待的秒数（0 = 立即可发）。"""
        now = time.monotonic()
        if self._backoff_until > now:
            return self._backoff_until - now
        return 0.0

    def acquire(self):
        """阻塞直到允许发请求。调用方在发 LLM 请求前调。"""
        wait = self.should_wait()
        if wait > 0:
            time.sleep(wait)
```

- [ ] **步骤 4：运行测试验证它们通过**

```
pytest tests/test_rate_limit.py -v
```
预期：PASS（5 个测试）。

- [ ] **步骤 5：检查点**

---

## 任务 20：Kernel gRPC 客户端

**文件：**
- 创建：`runtime/agentos_runtime/kernel_client.py`
- 创建：`runtime/tests/test_kernel_client.py`

- [ ] **步骤 1：写失败测试（用假 stub）**

`runtime/tests/test_kernel_client.py`:
```python
from agentos_runtime.kernel_client import KernelClient


class FakeStub:
    def __init__(self):
        self.calls = []

    def StartSession(self, req, **kw):
        self.calls.append(("start", req.policy_path, req.sanitization_path))
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


def test_start_and_call():
    client = KernelClient("dummy.sock")
    client._stub = FakeStub()
    sid = client.start_session("p.yaml", "s.yaml")
    assert sid == "sess-fake"
    result = client.call_tool(sid, "fs_read", {"path": "x"})
    assert result["allowed"] is True
    assert result["result"] == {"content": "hi"}
```

- [ ] **步骤 2：运行测试验证它失败**

```
pytest tests/test_kernel_client.py -v
```
预期：FAIL —— 模块找不到。

- [ ] **步骤 3：实现客户端**

`runtime/agentos_runtime/kernel_client.py`:
```python
import json
import os

import grpc

from .pb import agentos_pb2 as pb
from .pb import agentos_pb2_grpc as pb_grpc


class KernelClient:
    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        self._channel = None
        self._stub = None

    def _ensure(self):
        if self._stub is None:
            target = f"unix:{self._socket_path}" if os.name != "nt" else f"file://{self._socket_path}"
            self._channel = grpc.insecure_channel(target)
            grpc.channel_ready_future(self._channel).result(timeout=10)
            self._stub = pb_grpc.KernelStub(self._channel)

    def start_session(self, policy_path: str, sanitization_path: str) -> str:
        self._ensure()
        resp = self._stub.StartSession(pb.StartSessionRequest(
            policy_path=policy_path, sanitization_path=sanitization_path))
        return resp.session_id

    def call_tool(self, session_id: str, tool: str, params: dict) -> dict:
        self._ensure()
        params_json = json.dumps(params) if params else ""
        resp = self._stub.CallTool(
            pb.CallToolRequest(session_id=session_id, tool=tool, params_json=params_json))
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

> **Windows socket 注意**：grpc-python 在 Windows 连 unix socket 可能要 `file://` 或 `unix:` 前缀。代码里按 os.name 做了分支；若仍连不上，手动试两种前缀。

- [ ] **步骤 4：运行测试验证它通过**

```
pytest tests/test_kernel_client.py -v
```
预期：PASS。

- [ ] **步骤 5：检查点**

---

## 任务 21：DeepSeek 客户端（含自适应 rate limit）

**文件：**
- 创建：`runtime/agentos_runtime/llm/base.py`
- 创建：`runtime/agentos_runtime/llm/deepseek.py`

- [ ] **步骤 1：LLM 基类接口**

`runtime/agentos_runtime/llm/base.py`:
```python
from typing import Protocol


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """返回 assistant 消息 dict（可能含 tool_calls）。"""
        ...
```

- [ ] **步骤 2：DeepSeek 实现（集成 rate limiter）**

`runtime/agentos_runtime/llm/deepseek.py`:
```python
import os

from openai import OpenAI, RateLimitError

from ..rate_limit import AdaptiveRateLimiter
from .base import LLMClient


class DeepSeekClient:
    """DeepSeek，走 OpenAI 兼容 API，集成自适应限流。"""

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = None,
                 rate_limiter: AdaptiveRateLimiter | None = None):
        key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self._client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        self._model = model
        self._limiter = rate_limiter or AdaptiveRateLimiter(initial_rpm=30)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        # 遇 429 自适应退避重试，最多 3 次
        for attempt in range(3):
            self._limiter.acquire()
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tools or None,
                )
                self._limiter.on_success()
                return self._to_dict(resp.choices[0].message)
            except RateLimitError:
                self._limiter.on_429()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def _to_dict(self, msg) -> dict:
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
预期：含 `content` 的响应 dict。配额/鉴权错就先修 key，循环跑通前别往下走。

- [ ] **步骤 4：检查点**

---

## 任务 22：工具 schema（暴露给 LLM）

**文件：**
- 创建：`runtime/agentos_runtime/tools.py`

- [ ] **步骤 1：定义工具 schema**

`runtime/agentos_runtime/tools.py`:
```python
# 注意：工具名用下划线，不是点号——函数名正则拒绝点号。
# 这些 schema 与 Go 侧 tools/fs_tools.go 的 Schema() 一一对应。
# 未来可从 Go 侧 Schema() 自动生成（消除手工同步漂移）。

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

- [ ] **步骤 2：检查点**

---

## 任务 23：ReAct 循环 + Runtime CLI

**文件：**
- 创建：`runtime/agentos_runtime/loop.py`
- 创建：`runtime/tests/test_loop.py`
- 创建：`runtime/agentos_runtime/cli.py`

**背景：** ReAct 循环。Runtime 通过 kernel_client 调工具（脱敏后的结果才回）。遇 denied 不重试，遇 errored 回传给 LLM。

- [ ] **步骤 1：写循环失败测试**

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
    def start_session(self, policy, sanitization):
        return "s1"
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
    result = run_agent("compute total", llm, kernel, policy="p", sanitization="s", max_steps=5)
    assert kernel.calls == [("fs_read", {"path": "a.txt"})]
    assert "42" in result


def test_loop_respects_max_steps():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": str(i), "type": "function",
            "function": {"name": "fs_list", "arguments": json.dumps({"path": "."})}}]}
        for i in range(100)
    ])
    kernel = FakeKernel()
    result = run_agent("loop", llm, kernel, policy="p", sanitization="s", max_steps=3)
    assert "step limit" in result.lower() or "max" in result.lower() or "quota" in result.lower()


def test_loop_handles_denied_tool():
    llm = FakeLLM([
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "fs_read", "arguments": json.dumps({"path": "/etc/shadow"})}}]},
        {"role": "assistant", "content": "Could not read. Done."},
    ])
    kernel = FakeKernel()
    kernel.call_tool = lambda *a: {"allowed": False, "errored": False, "message": "permission denied", "result": {}}
    result = run_agent("try", llm, kernel, policy="p", sanitization="s", max_steps=5)
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


def run_agent(task: str, llm, kernel, policy: str, sanitization: str, max_steps: int = 20) -> str:
    session_id = kernel.start_session(policy, sanitization)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for _ in range(max_steps):
        assistant = llm.chat(messages, TOOL_SCHEMAS)
        messages.append(assistant)

        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            return assistant.get("content", "(no content)")

        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            res = kernel.call_tool(session_id, name, args)
            messages.append(_format_tool_result(tc["id"], name, res))

    return f"Reached step limit ({max_steps}) without finishing."


def _format_tool_result(tool_call_id: str, name: str, res: dict) -> dict:
    if res.get("errored"):
        content = f"Tool error: {res.get('message', 'unknown')}"
    elif not res.get("allowed"):
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

- [ ] **步骤 4：运行测试验证它们通过**

```
pytest tests/test_loop.py -v
```
预期：PASS（3 个测试）。

- [ ] **步骤 5：实现 Runtime CLI**

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
    p.add_argument("--sanitization", required=True, help="Path to sanitization rules YAML.")
    p.add_argument("--socket", default="./agentos.sock", help="Kernel unix socket path.")
    p.add_argument("--max-steps", type=int, default=20)
    args = p.parse_args()

    kernel = KernelClient(args.socket)
    llm = DeepSeekClient()
    try:
        result = run_agent(args.task, llm, kernel,
                           policy=args.policy, sanitization=args.sanitization,
                           max_steps=args.max_steps)
        print("=== AGENT RESULT ===")
        print(result)
    finally:
        kernel.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
```

- [ ] **步骤 6：检查点**

---

# 阶段 5 — 集成、对抗测试、架构验证

## 任务 24：Demo 工作区夹具

**文件：**
- 创建：`examples/workspace/sales.csv`
- 创建：`policies/data_analyst.yaml`（受信目录副本）

- [ ] **步骤 1：创建示例数据（含敏感字段验证脱敏）**

`examples/workspace/sales.csv`:
```csv
date,product,amount,customer_id,phone
2026-01-05,Widget,120,C001,13812341234
2026-01-07,Gadget,80,C002,13987654321
2026-01-09,Widget,200,C003,13700001111
2026-01-12,Gadget,45,C004,13622223333
```

- [ ] **步骤 2：把受信 Policy 放到 policies/ 目录**

复制 `examples/policies/data_analyst.yaml` 到 `policies/data_analyst.yaml`（Server 白名单允许 `./policies` 和 `./examples/policies`）。

- [ ] **步骤 3：检查点**

---

## 任务 25：端到端集成测试（手动 runbook）

**背景：** 设计文档 §2.3 的 demo。无自动化测试（需活 LLM + 运行中 Kernel），是手动 runbook。

- [ ] **步骤 1：启动内核**

终端 1：
```
agentos.exe serve -socket ./agentos.sock -audit-dir ./audit
```
预期：`agentos kernel listening on ./agentos.sock`。

- [ ] **步骤 2：跑合法任务**

终端 2（仓库根，已设 `DEEPSEEK_API_KEY`）：
```
agentos-run --task "Read examples/workspace/sales.csv, compute the total amount, and write the result to examples/workspace/out/total.txt" --policy policies/data_analyst.yaml --sanitization examples/sanitization/pii_rules.yaml --socket ./agentos.sock
```
预期：agent 打印结果；`examples/workspace/out/total.txt` 含 `445`（120+80+200+45）。

- [ ] **步骤 3：检查审计日志**

```
agentos.exe audit show <./audit 里最近的 session id>
```
预期：行显示 `fs_read sales.csv [allowed]`、`fs_write out/total.txt [allowed]`、`session_started`，且 hash 链校验通过。

- [ ] **步骤 4：检查点** —— 三支柱 demo（能干活、被管住、可审计）正常路径跑通。

---

## 任务 26：对抗安全测试套件（护城河）

**文件：**
- 创建：`kernel/test/adversarial/adversarial_test.go`

**背景：** 差异化所在。直接打 Gate（真正的安全边界），确定性证明每个攻击被挡。含脱敏验证。

- [ ] **步骤 1：写对抗套件**

`kernel/test/adversarial/adversarial_test.go`:
```go
package adversarial

import (
	"path/filepath"
	"testing"

	"agentos/kernel/internal/policy"
	"agentos/kernel/internal/resource"
	"agentos/kernel/internal/sanitize"
)

func loadRealPolicy(t *testing.T) *policy.Gate {
	t.Helper()
	rel := filepath.Join("..", "..", "..", "..", "examples", "policies", "data_analyst.yaml")
	p, err := policy.LoadFromFile(rel)
	if err != nil {
		t.Fatalf("load policy: %v", err)
	}
	return policy.NewGate(p)
}

func TestAdversarialReadEtcShadow(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "/etc/shadow"}) {
		t.Fatal("must deny /etc/shadow")
	}
}

func TestAdversarialReadAbsWindowsSecret(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_read", resource.Resource{Type: "path", ID: "C:/Windows/System32/config/SAM"}) {
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
		if g.Allowed("fs_read", resource.Resource{Type: "path", ID: a}) {
			t.Fatalf("must deny traversal: %s", a)
		}
	}
}

func TestAdversarialWriteOutsideOutDir(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/sales.csv"}) {
		t.Fatal("must deny overwriting source data")
	}
	if g.Allowed("fs_write", resource.Resource{Type: "path", ID: "examples/workspace/evil.txt"}) {
		t.Fatal("must deny write outside out/")
	}
}

func TestAdversarialUnknownTool(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("shell_exec", resource.Resource{Type: "path", ID: "rm -rf /"}) {
		t.Fatal("must deny unknown action")
	}
}

func TestAdversarialUnknownResourceType(t *testing.T) {
	g := loadRealPolicy(t)
	// 没有任何 db_table 规则
	if g.Allowed("db_query", resource.Resource{Type: "db_table", ID: "orders"}) {
		t.Fatal("must deny unknown resource type")
	}
}

func TestAdversarialNetworkDisabled(t *testing.T) {
	g := loadRealPolicy(t)
	if g.Allowed("net_fetch", resource.Resource{Type: "http_url", ID: "https://evil.com/exfil"}) {
		t.Fatal("must deny network")
	}
}

// 脱敏对抗测试：敏感字段必须被处理
func TestAdversarialSanitizationMasksPII(t *testing.T) {
	rel := filepath.Join("..", "..", "..", "..", "examples", "sanitization", "pii_rules.yaml")
	s, err := sanitize.LoadFromFile(rel)
	if err != nil {
		t.Fatal(err)
	}
	out := s.Sanitize(map[string]any{
		"phone":       "13812341234",
		"customer_id": "C001",
		"remark":      "secret",
		"amount":      120,
	})
	if out["phone"] == "13812341234" {
		t.Error("phone must be masked")
	}
	if out["customer_id"] == "C001" {
		t.Error("customer_id must be hashed")
	}
	if _, ok := out["remark"]; ok {
		t.Error("remark must be redacted (removed)")
	}
	if out["amount"] != 120 {
		t.Error("amount (non-PII) must be untouched")
	}
}
```

- [ ] **步骤 2：跑套件**

```
go test ./kernel/test/adversarial/ -v
```
预期：全部 8 个对抗测试 PASS（每个断言一次拒绝或脱敏）。任一失败 = 安全洞，修完再继续。

- [ ] **步骤 3：检查点** —— 护城河被证明。

---

## 任务 27：架构验证测试（开闭原则证明）

**文件：**
- 创建：`kernel/test/architecture/open_closed_test.go`

**背景：** 设计文档 §14.4 成功标准——"加新工具时 Kernel 核心零改动"。这个测试加一个 `db_query` 桩工具，证明 Pipeline/Gate/Server 无需改动即可接纳它。**这是 v2.3 最核心的架构承诺的可执行证明。**

- [ ] **步骤 1：写架构验证测试**

`kernel/test/architecture/open_closed_test.go`:
```go
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

	// 允许查询 sales.orders
	resp := pipe.Call(sess, "db_query", map[string]any{"table": "sales.orders"})
	if !resp.Allowed {
		t.Fatal("db_query on sales.orders must be allowed by existing Gate")
	}

	// 拒绝查询未授权的表
	resp = pipe.Call(sess, "db_query", map[string]any{"table": "finance.salaries"})
	if resp.Allowed {
		t.Fatal("db_query on finance.salaries must be denied")
	}

	// 事件正常发布
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
```

- [ ] **步骤 2：跑测试**

```
go test ./kernel/test/architecture/ -v
```
预期：PASS。这证明加 `db_query`（全新资源类型 `db_table`）时 Pipeline/Gate/EventBus 都不用改——开闭原则成立。

- [ ] **步骤 3：检查点** —— 架构承诺被可执行证明。

---

## 任务 28：按成功标准最终验证

- [ ] **步骤 1：跑全部 Go 测试**

```
go test ./...
```
预期：所有包 PASS（policy、sanitize、audit、eventbus、sandbox、tools、session、scheduler、pipeline、adversarial、architecture）。

- [ ] **步骤 2：跑全部 Python 测试**

```
cd runtime && pytest -v
```
预期：全部 PASS（kernel_client、rate_limit、loop）。

- [ ] **步骤 3：重跑端到端 demo（任务 25）**

确认：任务完成 → `out/total.txt` = 445 → 审计显示 allowed 调用 + session_started → hash 链校验通过。

- [ ] **步骤 4：重跑对抗套件（任务 26）**

确认：8 个攻击/脱敏场景全部正确（拒绝或脱敏）。

- [ ] **步骤 5：重跑架构验证（任务 27）**

确认：加 db_query 桩工具，Kernel 核心零改即工作。

- [ ] **步骤 6：最终检查点**

MVP（v2.3）完成。设计文档 §14 成功标准全部满足：
1. ✅ 功能：agent 跑通数据分析任务（读 → 脱敏 → 分析 → 写）
2. ✅ 安全：脱敏有效 + 对抗测试全过
3. ✅ 可审计：审计 hash 链完整，通过订阅事件产生
4. ✅ 架构：加新工具时 Kernel 核心零改动（任务 27 证明）
5. ✅ 并发：Scheduler 信号量工作，Account 超限硬终止
6. ✅ 认证：socket 权限 0600 + Policy 白名单生效

**技术架构与安全机制被验证。** 下一步：阶段 1（多 agent 调度）。

---

## 自查（写完后运行 —— 结果）

**1. 设计文档（v2.3 spec）覆盖：**

- §3.1 分层架构 → 任务 16-17（Server/CLI）、任务 19-23（Runtime）。✓
- §3.2 进程模型 → 任务 16、20。✓
- §3.3 gRPC over unix socket → 任务 3、17、20。✓
- §4.1 脱敏层 → 任务 6（Sanitizer）。✓
- §4.2 权限 Resource 泛化 → 任务 4（Resource）、5（Gate）。✓
- §4.3 沙箱 + 接口预留 → 任务 9（Sandbox 接口 + InProcess + Resolve）。✓
- §4.4 审计 hash 链 → 任务 7（Ledger）、14（Subscriber）。✓
- §5 工具自描述抽象 → 任务 10（Tool 接口 + fs 工具）。✓
- §5.4 开闭原则验证 → 任务 27（架构测试）。✓
- §6.1 Pipeline 6 步 → 任务 13（Pipeline）。✓
- §6.2 EventBus → 任务 8。✓
- §7.1 Scheduler → 任务 12。✓
- §7.2 Account/ResourceQuota → 任务 11。✓
- §7.3 Executor 接口 → spec 说"MVP 不实现"，计划里也未建（一致）。✓
- §7.4 rate limit 选项 Z（Runtime 侧）→ 任务 19。✓
- §8 Runtime（LLM 抽象 + ReAct）→ 任务 21、23。✓
- §9 状态持久化（原子写）→ 任务 10 fs_write 原子写 + 任务 11 Snapshot 接口。✓
- §10 Kernel 认证 → 任务 15（Authenticator + Policy 白名单）、任务 17（socket 0600）。✓
- §10.3 会话启动审计 → 任务 14（session.started 事件订阅）。✓
- §11 错误处理 → 任务 13（denied/errored/quota 事件）、任务 23（loop 处理 denied）。✓
- §12 测试（单元/集成/对抗）→ 各任务 TDD + 任务 25 集成 + 任务 26 对抗。✓
- §14 成功标准 → 任务 28 最终验证。✓

**2. 占位符扫描：** 无 TBD/TODO。任务 14、15 的"无独立测试，由集成测试覆盖"是显式说明，非占位符。✓

**3. 类型/名字一致性：**
- 工具名 `fs_read`/`fs_write`/`fs_list` 在 Go（任务 10）、Python（任务 22）一致。✓
- `resource.Resource{Type, ID}` 在任务 4、5、10、13、26、27 一致使用。✓
- `policy.Rule{ResourceType, Pattern, Actions}` 在任务 4、5、13、27 一致。✓
- `session.Session` 字段（ID/Policy/Gate/Sanitizer/Account/Ledger）在任务 11、13、16 一致。✓
- `pipeline.Response{Allowed, Errored, Message, Result}` 在任务 13、16 一致。✓
- `eventbus.Event.Type` 值（tool.called/denied/errored、session.started/ended、quota.exceeded）在任务 8、13、14、16 一致。✓
- proto 字段 Go 名（SessionId/PolicyPath/SanitizationPath/ParamsJson/ResultJson）在任务 16 核对提示。✓

**4. 循环依赖处理：** 任务 16 步骤 3-4 明确处理了 session ↔ pipeline 循环依赖（Pipeline 由 Server 持有，不放 Session）。✓

全部检查通过。计划就绪。
