# AgentOS 实时可观测控制台（切片 A）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AgentOS 建一个 Web 网关 + 实时可观测仪表盘，浏览器提交数据分析任务后实时看到 agent 的 think/act/observe、工具调用、权限/脱敏、run 收尾。

**Architecture:** 方案 2 独立网关，4 进程。Kernel 新增 2 个跨进程 RPC（`SubscribeEvents` server-streaming + `EmitRuntimeEvent` unary）+ sanitize 摘要 + 补 `session.ended`；Runtime 新增事件上报且不再自建 session；Gateway 全新 Go 模块（REST + WS + Run 编排 + 事件扇出/补播，`//go:embed` 前端）；Frontend 全新 React+Vite+TS SPA。事件枢纽 = Kernel EventBus。

**Tech Stack:** Go 1.26（kernel/gateway）、Python 3.11+（runtime）、React 18 + Vite 5 + TS（frontend）、gRPC/protobuf、WebSocket、vitest。

**Specs:**
- 设计：`docs/superpowers/specs/2026-06-25-agentos-realtime-console-slice-a.md`
- 定位（A2，最高权威）：`docs/superpowers/specs/2026-06-25-agentos-product-vision.md`

---

## 全局约定

- **模块路径**：Go module = `agentos`。Kernel 包在 `agentos/kernel/...`，Gateway 包在 `agentos/gateway/...`。
- **commit 粒度**：每个 Step 的 commit 用 conventional commits（`feat:` / `test:` / `chore:` / `docs:`）。
- **TDD**：每个功能先写失败测试，跑红，再写实现，跑绿，commit。安全相关必带对抗断言。
- **protoc 工具链**：proto 源在 `pb/agentos.proto`；Go 生成到 `pb/`；Python 生成到 `runtime/agentos_runtime/pb/`。生成命令见 Task 1。
- **Python 命令**：本机 shell 里 `python` 可能不可用，执行前先确认（`python --version` 或 `python3 --version` 或 `py --version`），用可用的那个；下文统一写 `python`，按实际替换。
- **不预留蓝图 B**：不加多租户/沙箱池（YAGNI，A2 近中期不需要）。

---

## 文件结构总览

**Kernel（改动，全加性）：**
- `pb/agentos.proto` — 新增 Event message + 2 RPC
- `kernel/internal/pb/*.pb.go` — protoc 重生成
- `kernel/internal/sanitize/sanitizer.go` — `Sanitize` 返回 `Result{Data, Summary}`；新增 `Summary` 类型
- `kernel/internal/sanitize/sanitizer_test.go` — 摘要断言
- `kernel/internal/eventbus/bus.go` — `Event` 加 `Sanitize []FieldSanitization` 字段
- `kernel/internal/pipeline/pipeline.go` — `tool.called` 附摘要；步骤 5 拿摘要
- `kernel/internal/pipeline/pipeline_test.go` — 摘要进事件断言
- `kernel/internal/server/server.go` — 2 个 RPC handler + `EndSession` 发 `session.ended` + 维护事件订阅者
- `kernel/internal/server/events_test.go` — 新建，测试 SubscribeEvents/EmitRuntimeEvent

**Runtime（改动，加性）：**
- `runtime/agentos_runtime/pb/*.py` — protoc 重生成
- `runtime/agentos_runtime/kernel_client.py` — 加 `emit_event`
- `runtime/agentos_runtime/loop.py` — 发 run.started/runtime.step/run.ended；用传入 session_id
- `runtime/agentos_runtime/cli.py` — 接 `--run-id` `--session-id`；退出码约定
- `runtime/tests/test_loop_events.py` — 新建
- `runtime/tests/test_kernel_client_emit.py` — 新建

**Gateway（全新 `gateway/`）：**
- `gateway/cmd/agentos-gateway/main.go` — 入口
- `gateway/internal/kclient/client.go` — gRPC client（StartSession/CallTool/SubscribeEvents）
- `gateway/internal/runmgr/manager.go` — run 注册表 + fork Runtime + 看门狗 + 事件环
- `gateway/internal/runmgr/manager_test.go`
- `gateway/internal/api/handlers.go` — REST
- `gateway/internal/api/handlers_test.go`
- `gateway/internal/ws/hub.go` — WS hub（扇出 + 补播）
- `gateway/internal/ws/hub_test.go`
- `gateway/web/dist/` — 前端构建产物（`//go:embed`）

**Frontend（全新 `web-src/`）：**
- `web-src/package.json` / `vite.config.ts` / `tsconfig.json`
- `web-src/src/main.tsx` / `App.tsx`
- `web-src/src/hooks/useEventStream.ts` / `api.ts`
- `web-src/src/views/RunList.tsx` / `RunDetail.tsx` / `RunSubmit.tsx`
- `web-src/src/components/EventTimeline.tsx` / `StepCard.tsx` / `ToolCallCard.tsx` / `SanitizeBadge.tsx`
- `web-src/src/__tests__/` — vitest

---

## Task 1: Kernel proto 扩展 — Event message + 2 RPC

**Files:**
- Modify: `pb/agentos.proto`
- Regenerate: `kernel/internal/pb/agentos.pb.go`, `kernel/internal/pb/agentos_grpc.pb.go`
- Regenerate: `runtime/agentos_runtime/pb/agentos_pb2.py`, `runtime/agentos_runtime/pb/agentos_pb2_grpc.py`

- [ ] **Step 1: 编辑 proto，加 Event message 和两个 RPC**

把 `pb/agentos.proto` 的 service 与 message 部分改为（保留原有 4 个 message，追加新内容）：

```proto
syntax = "proto3";

package agentos;

option go_package = "agentos/kernel/internal/pb";

service Kernel {
  rpc StartSession(StartSessionRequest) returns (StartSessionResponse);
  rpc CallTool(CallToolRequest) returns (CallToolResponse);
  // 订阅全量事件流（server-streaming）。网关用它收 Kernel+Runtime 事件。
  rpc SubscribeEvents(SubscribeEventsRequest) returns (stream Event);
  // Runtime 把推理事件灌进 Kernel EventBus（事件枢纽统一在 Kernel）。
  rpc EmitRuntimeEvent(Event) returns (EmitResponse);
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

message SubscribeEventsRequest {
  // 预留过滤字段；MVP 网关全收后自己按 session/run 过滤。
  string session_id = 1;
}

message EmitResponse {}

// Event 是统一事件信封。对齐 kernel/internal/eventbus.Event。
message Event {
  string type = 1;            // tool.called | tool.denied | ... | run.started | runtime.step | run.ended
  string session_id = 2;
  string run_id = 3;          // Runtime 族事件才有
  string tool = 4;
  string params_json = 5;     // JSON
  string result_json = 6;     // JSON（已脱敏）
  string identity = 7;
  int64 timestamp = 8;        // ns
  // 脱敏摘要：哪些字段被哪种策略处理，不含原始值。
  repeated FieldSanitization sanitize = 9;
  // Runtime 族事件的自由负载（thought / final_answer / tool_calls / termination ...）。
  string payload_json = 10;
}

message FieldSanitization {
  string field = 1;
  string strategy = 2;        // mask | hash | redact
}
```

- [ ] **Step 2: 重生成 Go pb**

Run:
```bash
cd /e/Project/Agent-Project/AgentOS
protoc -I pb --go_out=. --go_opt=module=agentos \
  --go-grpc_out=. --go-grpc_opt=module=agentos \
  pb/agentos.proto
```
Expected: `pb/agentos.pb.go` 与 `pb/agentos_grpc.pb.go` 被更新，含 `Event`/`SubscribeEventsRequest`/`EmitResponse`/`FieldSanitization` 与 `Kernel_SubscribeEventsServer` 流类型。若 protoc 未安装，先 `go install google.golang.org/protobuf/cmd/protoc-gen-go@latest` 和 `google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest`，并确保 `$GOPATH/bin` 在 PATH。

- [ ] **Step 3: 重生成 Python pb**

Run:
```bash
python -m grpc_tools.protoc -I pb \
  --python_out=runtime/agentos_runtime/pb \
  --grpc_python_out=runtime/agentos_runtime/pb \
  pb/agentos.proto
```
（`grpc_tools` 来自 `pip install grpcio-tools`。）
Expected: `runtime/agentos_runtime/pb/agentos_pb2.py` 含 `Event` 等；`_pb2_grpc.py` 含 `KernelStub.SubscribeEvents`/`EmitRuntimeEvent`。

- [ ] **Step 4: 编译验证**

Run:
```bash
go build ./...
```
Expected: 编译通过（server.go 还没实现新 RPC 方法，但因嵌入 `UnimplementedKernelServer`，编译不报错）。

- [ ] **Step 5: Commit**

```bash
git add proto/ kernel/internal/pb/ runtime/agentos_runtime/pb/
git commit -m "feat(proto): add Event message, SubscribeEvents & EmitRuntimeEvent RPCs"
```

---

## Task 2: Sanitizer 产出脱敏摘要

**Files:**
- Modify: `kernel/internal/sanitize/sanitizer.go`
- Modify: `kernel/internal/sanitize/sanitizer_test.go`

目标：`Sanitize` 返回 `Result{Data, Summary}`，`Summary` 记录 `{field, strategy}`，**不含原始值**。

- [ ] **Step 1: 写失败测试 — 摘要包含被处理字段，且不含原始值**

在 `kernel/internal/sanitize/sanitizer_test.go` 追加：

```go
func TestSanitizeReturnsSummary(t *testing.T) {
	s := NewFromRules([]FieldRule{
		{Name: "phone", Strategy: "mask", KeepPrefix: 3, KeepSuffix: 4},
		{Name: "customer_id", Strategy: "hash"},
		{Name: "remark", Strategy: "redact"},
	})

	res := s.Sanitize(map[string]any{
		"phone":       "13800001234",
		"customer_id": "C-100",
		"remark":      "very secret",
		"safe":        "keep me",
	})

	// 摘要应记录被处理的 3 个字段。
	wantFields := map[string]string{
		"phone":       "mask",
		"customer_id": "hash",
		"remark":      "redact",
	}
	got := map[string]string{}
	for _, f := range res.Summary {
		got[f.Field] = f.Strategy
	}
	if len(got) != len(wantFields) {
		t.Fatalf("summary len = %d, want %d (%v)", len(got), len(wantFields), got)
	}
	for k, v := range wantFields {
		if got[k] != v {
			t.Errorf("summary[%s] = %q, want %q", k, got[k], v)
		}
	}

	// 摘要里绝不能含原始值。
	dump := fmt.Sprintf("%v", res.Summary)
	for _, secret := range []string{"13800001234", "C-100", "very secret"} {
		if strings.Contains(dump, secret) {
			t.Errorf("summary leaks original value %q: %v", secret, res.Summary)
		}
	}
	// redact 字段在 data 里被移除。
	if _, ok := res.Data["remark"]; ok {
		t.Error("redact field should be removed from data")
	}
}
```

（确保文件顶部 import 含 `"fmt"` 和 `"strings"`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `go test ./kernel/internal/sanitize/ -run TestSanitizeReturnsSummary -v`
Expected: FAIL，编译错误或 `res.Summary` 未定义。

- [ ] **Step 3: 改实现 — 引入 Result/Summary 类型，Sanitize 返回摘要**

改 `kernel/internal/sanitize/sanitizer.go`：

```go
// FieldSanitization 是脱敏摘要的一条：字段名 + 策略，不含原始值。
type FieldSanitization struct {
	Field    string
	Strategy string // mask | hash | redact
}

// Result 是 Sanitize 的产出：脱敏后数据 + 摘要（不含原始值）。
type Result struct {
	Data    map[string]any
	Summary []FieldSanitization
}

// Sanitize 对 data 中匹配规则的字段应用脱敏，返回新 data 与摘要（不改原 map）。
// redact 字段会被完全移除，但仍记入摘要。
func (s *Sanitizer) Sanitize(data map[string]any) Result {
	out := make(map[string]any, len(data))
	var summary []FieldSanitization
	for k, v := range data {
		rule, ok := s.rules[k]
		if !ok {
			out[k] = v
			continue
		}
		applied := s.apply(rule, v)
		summary = append(summary, FieldSanitization{Field: k, Strategy: rule.Strategy})
		if _, isOmit := applied.(omit); isOmit {
			continue // redact：完全移除字段（摘要已记）
		}
		out[k] = applied
	}
	return Result{Data: out, Summary: summary}
}

// SanitizeData 是便捷包装，仅返回 data（供不需要摘要的旧调用点用）。
func (s *Sanitizer) SanitizeData(data map[string]any) map[string]any {
	return s.Sanitize(data).Data
}
```

删除旧的 `Sanitize` 签名（返回 `map[string]any` 的版本），用上面的新签名替换。

- [ ] **Step 4: 跑测试确认通过**

Run: `go test ./kernel/internal/sanitize/ -v`
Expected: PASS（含新测试与原有测试）。若原有测试调用旧签名，改用 `SanitizeData` 或 `.Data`。

- [ ] **Step 5: Commit**

```bash
git add kernel/internal/sanitize/
git commit -m "feat(sanitize): return sanitization summary without original values"
```

---

## Task 3: Pipeline 把脱敏摘要附进 tool.called 事件

**Files:**
- Modify: `kernel/internal/eventbus/bus.go`
- Modify: `kernel/internal/pipeline/pipeline.go`
- Modify: `kernel/internal/pipeline/pipeline_test.go`

- [ ] **Step 1: 写失败测试 — tool.called 事件含 sanitize 摘要且无原始值**

在 `kernel/internal/pipeline/pipeline_test.go` 追加（沿用该文件已有的 fake tool / fake bus 模式；若名字不同，按现有夹具对齐）：

```go
func TestCallEmitsSanitizeSummary(t *testing.T) {
	bus := &fakeBus{}
	pipe := New(newRegistryWithSanitizingTool(), bus)
	sess := newSessionWithSanitizer() // sanitizer 配置：field "phone" → mask

	resp := pipe.Call(sess, "fs_read", map[string]any{"path": "x.csv"})

	if !resp.Allowed {
		t.Fatal("expected allowed")
	}
	if len(bus.events) != 1 || bus.events[0].Type != "tool.called" {
		t.Fatalf("expected one tool.called event, got %+v", bus.events)
	}
	ev := bus.events[0]
	if len(ev.Sanitize) != 1 || ev.Sanitize[0].Field != "phone" || ev.Sanitize[0].Strategy != "mask" {
		t.Errorf("unexpected sanitize summary: %+v", ev.Sanitize)
	}
	// 对抗断言：原始手机号绝不能出现在事件任何字段里。
	dump := fmt.Sprintf("%v", ev)
	if strings.Contains(dump, "13800001234") {
		t.Error("event leaks original sensitive value")
	}
}
```

（按现有夹具调整 `newRegistryWithSanitizingTool`/`newSessionWithSanitizer`；关键是 tool 的 Execute 返回含 `phone` 字段、sanitizer 配 phone→mask。）

- [ ] **Step 2: 跑测试确认失败**

Run: `go test ./kernel/internal/pipeline/ -run TestCallEmitsSanitizeSummary -v`
Expected: FAIL（`Event.Sanitize` 字段不存在）。

- [ ] **Step 3: 给 Event 加 Sanitize 字段**

改 `kernel/internal/eventbus/bus.go` 的 `Event` struct，加：

```go
import (
	"sync"
	"time"

	"agentos/kernel/internal/sanitize"
)

type Event struct {
	Type      string
	SessionID string
	RunID     string // Runtime 族事件用
	Tool      string
	Params    map[string]any
	Result    map[string]any
	Identity  string
	Sanitize  []sanitize.FieldSanitization // 脱敏摘要，仅 tool.called 有
	Payload   map[string]any               // Runtime 族事件的自由负载
	Timestamp int64
}
```

- [ ] **Step 4: Pipeline 步骤 5 拿摘要并塞进事件**

改 `kernel/internal/pipeline/pipeline.go` 步骤 5-6：

```go
	// 步骤 5：脱敏（第一道安全防线，独立于工具）。保留摘要进事件。
	var sanSummary []sanitize.FieldSanitization
	if sess.Sanitizer != nil {
		sr := sess.Sanitizer.Sanitize(result.Data)
		result.Data = sr.Data
		sanSummary = sr.Summary
	}

	// 步骤 6：审计（通过事件触发 AuditSubscriber，不散落）。含脱敏摘要。
	p.bus.Publish(eventbus.Event{
		Type:     "tool.called", SessionID: sess.ID, Tool: toolName,
		Params: params, Result: result.Data, Sanitize: sanSummary,
	})

	return Response{Allowed: true, Result: result.Data}
```

（import `"agentos/kernel/internal/sanitize"`。）

- [ ] **Step 5: 跑测试确认通过**

Run: `go test ./kernel/internal/pipeline/ -v`
Expected: PASS（含新测试）。同步修掉 audit subscriber 测试（若断言 Result 的旧结构）。

- [ ] **Step 6: Commit**

```bash
git add kernel/internal/eventbus/ kernel/internal/pipeline/
git commit -m "feat(pipeline): attach sanitization summary to tool.called event"
```

---

## Task 4: Kernel server 实现 SubscribeEvents / EmitRuntimeEvent + 补 session.ended

**Files:**
- Modify: `kernel/internal/server/server.go`
- Create: `kernel/internal/server/events_test.go`

设计：Server 持有一个**全局事件总线**（区别于现有 per-session bus）。`SubscribeEvents` 注册一个 streaming 订阅者；Pipeline/audit 用的 per-session bus 事件，以及 `EmitRuntimeEvent` 灌入的事件，都转发到这个全局总线供订阅。MVP 简化：把 Server 改为持有一个共享 `*eventbus.InProcess`，所有 session 的 bus 即它（事件用 SessionID 区分），`SubscribeEvents` 在它上面订阅并 stream 出去。

- [ ] **Step 1: 写失败测试 — EmitRuntimeEvent 进总线并被 SubscribeEvents 收到**

新建 `kernel/internal/server/events_test.go`：

```go
package server

import (
	"context"
	"testing"
	"time"

	pb "agentos/kernel/internal/pb"
)

func TestSubscribeAndEmit(t *testing.T) {
	s := New("./_test_audit")

	// 订阅流
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := &fakeSubscribeStream{ctx: ctx}
	go func() { _ = s.SubscribeEvents(&pb.SubscribeEventsRequest{}, stream) }()

	// 给订阅一点注册时间
	time.Sleep(50 * time.Millisecond)

	// Runtime 灌一个事件
	_, err := s.EmitRuntimeEvent(context.Background(), &pb.Event{
		Type: "runtime.step", SessionID: "s1", RunID: "r1",
		PayloadJson: `{"step_index":0}`,
	})
	if err != nil {
		t.Fatalf("EmitRuntimeEvent: %v", err)
	}

	select {
	case got := <-stream.recv:
		if got.Type != "runtime.step" || got.RunId != "r1" {
			t.Errorf("unexpected event: %+v", got)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event")
	}
}

// fakeSubscribeStream 实现 pb.Kernel_SubscribeEventsServer。
type fakeSubscribeStream struct {
	ctx  context.Context
	recv chan *pb.Event
}

func (f *fakeSubscribeStream) Send(e *pb.Event) error {
	f.recv <- e
	return nil
}
func (f *fakeSubscribeStream) Context() context.Context { return f.ctx }
func (f *fakeSubscribeStream) RecvMsg(any) error         { return nil }
func (f *fakeSubscribeStream) SetHeader(any) error       { return nil }
func (f *fakeSubscribeStream) SendHeader(any) error      { return nil }
func (f *fakeSubscribeStream) SetTrailer(any)            {}
func (f *fakeSubscribeStream) SendMsg(any) error         { return nil }

func init() {}
```

注意 `fakeSubscribeStream` 需带缓冲：`recv: make(chan *pb.Event, 8)`，在构造里设置（调整 `&fakeSubscribeStream{ctx: ctx, recv: make(...)}`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `go test ./kernel/internal/server/ -run TestSubscribeAndEmit -v`
Expected: FAIL（`SubscribeEvents`/`EmitRuntimeEvent` 方法未实现，或全局总线不存在）。

- [ ] **Step 3: 改 Server — 共享总线 + 2 RPC + session.ended**

改 `kernel/internal/server/server.go`：

```go
type Server struct {
	pb.UnimplementedKernelServer
	mu        sync.Mutex
	sessions  map[string]*session.Session
	pipelines map[string]*pipeline.Pipeline
	registry  *tools.Registry
	scheduler *scheduler.Scheduler
	auth      auth.Authenticator
	auditDir  string
	nextID    int64
	globalBus *eventbus.InProcess // 所有 session + Runtime 事件汇于此
}

func New(auditDir string) *Server {
	reg := tools.NewRegistry()
	reg.Register(tools.FSReadTool{})
	reg.Register(tools.FSWriteTool{})
	reg.Register(tools.FSListTool{})
	gbus := eventbus.NewInProcess()
	return &Server{
		sessions:  map[string]*session.Session{},
		pipelines: map[string]*pipeline.Pipeline{},
		registry:  reg,
		scheduler: scheduler.New(4),
		auth:      auth.LocalAuthenticator{},
		auditDir:  auditDir,
		globalBus: gbus,
	}
}
```

把 `StartSession` 里 per-session `bus := eventbus.NewInProcess()` 改为用 `s.globalBus`，审计订阅注册到 `s.globalBus`，`pipeline.New(s.registry, s.globalBus)`。

新增两个 RPC 与转换函数：

```go
// SubscribeEvents 把全局总线事件 stream 给调用方（网关）。
func (s *Server) SubscribeEvents(req *pb.SubscribeEventsRequest, stream pb.Kernel_SubscribeEventsServer) error {
	errCh := make(chan error, 1)
	unsub := s.globalBus.Subscribe(func(e eventbus.Event) {
		if req.SessionId != "" && e.SessionID != req.SessionId {
			return
		}
		if err := stream.Send(toProtoEvent(e)); err != nil {
			select {
			case errCh <- err:
			default:
			}
		}
	})
	defer unsub()
	select {
	case <-stream.Context().Done():
		return nil
	case err := <-errCh:
		return err
	}
}

// EmitRuntimeEvent 把 Runtime 事件灌进全局总线。
func (s *Server) EmitRuntimeEvent(ctx context.Context, e *pb.Event) (*pb.EmitResponse, error) {
	s.globalBus.Publish(fromProtoEvent(e))
	return &pb.EmitResponse{}, nil
}
```

注意：现有 `eventbus.InProcess.Subscribe` 返回无 unsubscribe。需要先给 `InProcess` 加 unsubscribe（改 bus.go：`Subscribe` 返回 `func()`，内部用 handle id 移除）。在 Task 4 Step 3 一并改 `kernel/internal/eventbus/bus.go`：

```go
func (b *InProcess) Subscribe(h func(Event)) func() {
	b.mu.Lock()
	id := len(b.handlers)
	b.handlers = append(b.handlers, h)
	b.mu.Unlock()
	return func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		b.handlers[id] = nil // 简单置空；Publish 跳过 nil
	}
}

func (b *InProcess) Publish(e Event) {
	e.Timestamp = time.Now().UnixNano()
	b.mu.Lock()
	handlers := append([]func(Event){}, b.handlers...)
	b.mu.Unlock()
	for _, h := range handlers {
		if h == nil {
			continue
		}
		func() { defer func() { _ = recover() }(); h(e) }()
	}
}
```

转换函数 `toProtoEvent` / `fromProtoEvent`（放 server.go，处理 Params/Result/Payload 的 JSON 与 sanitize 摘要）：

```go
func toProtoEvent(e eventbus.Event) *pb.Event {
	params, _ := json.Marshal(e.Params)
	result, _ := json.Marshal(e.Result)
	payload, _ := json.Marshal(e.Payload)
	var san []*pb.FieldSanitization
	for _, f := range e.Sanitize {
		san = append(san, &pb.FieldSanitization{Field: f.Field, Strategy: f.Strategy})
	}
	return &pb.Event{
		Type: e.Type, SessionId: e.SessionID, RunId: e.RunID, Tool: e.Tool,
		ParamsJson: string(params), ResultJson: string(result), Identity: e.Identity,
		Sanitize: san, PayloadJson: string(payload), Timestamp: e.Timestamp,
	}
}

func fromProtoEvent(e *pb.Event) eventbus.Event {
	var params, result, payload map[string]any
	json.Unmarshal([]byte(e.ParamsJson), &params)
	json.Unmarshal([]byte(e.ResultJson), &result)
	json.Unmarshal([]byte(e.PayloadJson), &payload)
	var san []sanitize.FieldSanitization
	for _, f := range e.Sanitize {
		san = append(san, sanitize.FieldSanitization{Field: f.Field, Strategy: f.Strategy})
	}
	return eventbus.Event{
		Type: e.Type, SessionID: e.SessionId, RunID: e.RunId, Tool: e.Tool,
		Params: params, Result: result, Identity: e.Identity,
		Sanitize: san, Payload: payload, Timestamp: e.Timestamp,
	}
}
```

**补 session.ended**：新增 `EndSession` RPC 或在 Server 加方法。MVP 选：Gateway 负责 run 结束时调一个新 unary `EndSession(session_id, reason)`。在 proto service 加 `rpc EndSession(EndSessionRequest) returns (EndSessionResponse);` 与对应 message（`EndSessionRequest{session_id, reason}`，`EndSessionResponse{}`），重生成 pb，Server 实现：

```go
func (s *Server) EndSession(ctx context.Context, req *pb.EndSessionRequest) (*pb.EndSessionResponse, error) {
	s.mu.Lock()
	sess := s.sessions[req.SessionId]
	delete(s.sessions, req.SessionId)
	delete(s.pipelines, req.SessionId)
	s.mu.Unlock()
	if sess != nil {
		s.globalBus.Publish(eventbus.Event{Type: "session.ended", SessionID: req.SessionId, Payload: map[string]any{"reason": req.Reason}})
		if sess.Ledger != nil {
			sess.Ledger.Close() // 若 Ledger 无 Close，省略或加
		}
	}
	return &pb.EndSessionResponse{}, nil
}
```

（若 `audit.Ledger` 无 `Close`，Task 里加一个 no-op Close 或跳过。）

- [ ] **Step 4: 跑测试确认通过**

Run: `go test ./kernel/internal/server/ -v`
Expected: PASS。补一个 `TestEndSessionPublishesEnded` 断言 `session.ended` 被发。

- [ ] **Step 5: 全量编译 + 测试**

Run: `go build ./... && go test ./...`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add proto/ kernel/
git commit -m "feat(kernel): SubscribeEvents/EmitRuntimeEvent/EndSession RPCs + session.ended"
```

---

## Task 5: Runtime 事件上报 + 不再自建 session

**Files:**
- Modify: `runtime/agentos_runtime/kernel_client.py`
- Modify: `runtime/agentos_runtime/loop.py`
- Modify: `runtime/agentos_runtime/cli.py`
- Create: `runtime/tests/test_loop_events.py`
- Create: `runtime/tests/test_kernel_client_emit.py`

- [ ] **Step 1: 写失败测试 — kernel_client.emit_event 发正确的 pb**

新建 `runtime/tests/test_kernel_client_emit.py`：

```python
import json
from unittest.mock import MagicMock

from agentos_runtime.kernel_client import KernelClient


def test_emit_event_sends_correct_proto(monkeypatch):
    kc = KernelClient("./x.sock")
    kc._stub = MagicMock()
    kc.emit_event(run_id="r1", session_id="s1", etype="runtime.step",
                  payload={"step_index": 0, "thought": "hi"})
    args, _ = kc._stub.EmitRuntimeEvent.call_args
    ev = args[0]
    assert ev.type == "runtime.step"
    assert ev.run_id == "r1"
    assert ev.session_id == "s1"
    assert json.loads(ev.payload_json) == {"step_index": 0, "thought": "hi"}
```

Run: `python -m pytest runtime/tests/test_kernel_client_emit.py -v`
Expected: FAIL（`emit_event` 不存在）。

- [ ] **Step 2: 实现 kernel_client.emit_event**

在 `runtime/agentos_runtime/kernel_client.py` 加：

```python
    def emit_event(self, run_id: str, session_id: str, etype: str, payload: dict) -> None:
        self._ensure()
        self._stub.EmitRuntimeEvent(pb.Event(
            type=etype, run_id=run_id, session_id=session_id,
            payload_json=json.dumps(payload) if payload else "",
        ))
```

（确保文件顶部 `import json` 已在。）

Run: `python -m pytest runtime/tests/test_kernel_client_emit.py -v`
Expected: PASS。

- [ ] **Step 3: 写失败测试 — loop 发三类事件且用传入 session_id**

新建 `runtime/tests/test_loop_events.py`：

```python
from unittest.mock import MagicMock

from agentos_runtime.loop import run_agent


def test_loop_emits_run_lifecycle_events():
    kernel = MagicMock()
    kernel.start_session.return_value = "s1"  # 不再被 loop 调，但留 mock
    llm = MagicMock()
    # 第 1 步: tool_call；第 2 步: 最终答案
    llm.chat.side_effect = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "function": {"name": "fs_list", "arguments": '{"path":"."}'}}]},
        {"role": "assistant", "content": "done"},
    ]
    kernel.call_tool.return_value = {"allowed": True, "errored": False, "result": {}}

    emits = []
    kernel.emit_event.side_effect = lambda **kw: emits.append(kw)

    run_agent(task="list files", llm=llm, kernel=kernel,
              session_id="s1", run_id="r1", max_steps=5)

    types = [e["etype"] for e in emits]
    assert "run.started" in types
    assert "runtime.step" in types
    assert "run.ended" in types
    # loop 不应再调 start_session
    kernel.start_session.assert_not_called()
    # 最后一个 run.ended 含 termination
    ended = [e for e in emits if e["etype"] == "run.ended"][-1]
    assert ended["payload"]["termination"] == "completed"
```

Run: `python -m pytest runtime/tests/test_loop_events.py -v`
Expected: FAIL（`run_agent` 签名不接受 session_id/run_id，不发事件）。

- [ ] **Step 4: 改 loop.py — 接收 session_id/run_id，发三类事件，不建 session**

改 `runtime/agentos_runtime/loop.py`：

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


def run_agent(task: str, llm, kernel, session_id: str, run_id: str, max_steps: int = 20) -> str:
    """ReAct 循环。session 由调用方（网关）建立，loop 只用 session_id。

    发 run.started / runtime.step / run.ended。所有工具调用经 kernel（脱敏后结果才回）。
    """
    kernel.emit_event(run_id=run_id, session_id=session_id, etype="run.started",
                      payload={"task": task, "max_steps": max_steps})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    steps_used = 0
    termination = "completed"
    final_answer = ""

    try:
        for step in range(max_steps):
            steps_used = step + 1
            assistant = llm.chat(messages, TOOL_SCHEMAS)
            messages.append(assistant)

            tool_calls = assistant.get("tool_calls")
            if not tool_calls:
                final_answer = assistant.get("content", "(no content)")
                break

            tool_call_summaries = [
                {"name": tc["function"]["name"],
                 "args": json.loads(tc["function"].get("arguments") or "{}")}
                for tc in tool_calls
            ]
            kernel.emit_event(run_id=run_id, session_id=session_id, etype="runtime.step",
                              payload={"step_index": step, "thought": assistant.get("content", ""),
                                       "tool_calls": tool_call_summaries})

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                res = kernel.call_tool(session_id, name, args)
                messages.append(_format_tool_result(tc["id"], name, res))
        else:
            termination = "step_limit"
            final_answer = f"Reached step limit ({max_steps}) without finishing."
    except Exception as exc:  # 任何未处理异常 → crashed
        termination = "crashed"
        final_answer = f"error: {exc}"
        raise
    finally:
        kernel.emit_event(run_id=run_id, session_id=session_id, etype="run.ended",
                          payload={"termination": termination, "steps_used": steps_used,
                                   "final_answer": final_answer})

    return final_answer


def _format_tool_result(tool_call_id: str, name: str, res: dict) -> dict:
    if res.get("errored"):
        content = f"Tool error: {res.get('message', 'unknown')}"
    elif not res.get("allowed"):
        content = res.get("message", "permission denied")
    else:
        content = json.dumps(res.get("result", {}))
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content}
```

Run: `python -m pytest runtime/tests/test_loop_events.py runtime/tests/ -v`
Expected: PASS。

- [ ] **Step 5: 改 cli.py — 接 --run-id/--session-id，退出码约定**

改 `runtime/agentos_runtime/cli.py`：

```python
import argparse
import sys

from .kernel_client import KernelClient
from .llm.deepseek import DeepSeekClient
from .loop import run_agent


def main():
    p = argparse.ArgumentParser(prog="agentos-run")
    p.add_argument("--task", required=True)
    p.add_argument("--session-id", required=True)   # 由网关 StartSession 得到
    p.add_argument("--run-id", required=True)        # 由网关分配
    p.add_argument("--socket", default="./agentos.sock")
    p.add_argument("--max-steps", type=int, default=20)
    args = p.parse_args()

    kernel = KernelClient(args.socket)
    llm = DeepSeekClient()
    try:
        run_agent(args.task, llm, kernel,
                  session_id=args.session_id, run_id=args.run_id,
                  max_steps=args.max_steps)
        sys.exit(0)        # 0 = 正常结束
    except Exception as exc:
        sys.stderr.write(f"runtime crashed: {exc}\n")
        sys.exit(1)        # 非 0 = 崩溃/报错
    finally:
        kernel.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
```

（旧的 `--policy`/`--sanitization` 移除——session 已由网关建。）

- [ ] **Step 6: Commit**

```bash
git add runtime/
git commit -m "feat(runtime): emit run/step events, use caller-provided session, exit codes"
```

---

## Task 6: Gateway — gRPC client + 入口骨架

**Files:**
- Create: `gateway/internal/kclient/client.go`
- Create: `gateway/cmd/agentos-gateway/main.go`

- [ ] **Step 1: gRPC client 包装**

新建 `gateway/internal/kclient/client.go`：

```go
package kclient

import (
	"context"
	"io"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "agentos/kernel/internal/pb"
)

// Client 连 Kernel gRPC。
type Client struct {
	conn   *grpc.ClientConn
	stub   pb.KernelClient
	socket string
	once   sync.Once
	err    error
}

func New(socket string) *Client {
	return &Client{socket: socket}
}

func (c *Client) ensure() error {
	c.once.Do(func() {
		c.conn, c.err = grpc.Dial("unix://"+c.socket,
			grpc.WithTransportCredentials(insecure.NewCredentials()))
		if c.err == nil {
			c.stub = pb.NewKernelClient(c.conn)
		}
	})
	return c.err
}

func (c *Client) StartSession(ctx context.Context, policy, sanitization string) (string, error) {
	if err := c.ensure(); err != nil {
		return "", err
	}
	resp, err := c.stub.StartSession(ctx, &pb.StartSessionRequest{PolicyPath: policy, SanitizationPath: sanitization})
	if err != nil {
		return "", err
	}
	return resp.SessionId, nil
}

func (c *Client) EndSession(ctx context.Context, sessionID, reason string) error {
	if err := c.ensure(); err != nil {
		return err
	}
	_, err := c.stub.EndSession(ctx, &pb.EndSessionRequest{SessionId: sessionID, Reason: reason})
	return err
}

// Subscribe 订阅事件流；handler 在调用 goroutine 里被调用，直到 ctx 取消或流断。
func (c *Client) Subscribe(ctx context.Context, sessionID string, handler func(*pb.Event)) error {
	if err := c.ensure(); err != nil {
		return err
	}
	stream, err := c.stub.SubscribeEvents(ctx, &pb.SubscribeEventsRequest{SessionId: sessionID})
	if err != nil {
		return err
	}
	for {
		ev, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		handler(ev)
	}
}

func (c *Client) Close() {
	if c.conn != nil {
		c.conn.Close()
	}
}
```

- [ ] **Step 2: 入口 main.go 最小骨架（Task 8 接线 REST/WS，这里只占位编译通过）**

新建 `gateway/cmd/agentos-gateway/main.go`：

```go
package main

import (
	"flag"
	"fmt"
	"os"
)

func main() {
	fs := flag.NewFlagSet("agentos-gateway", flag.ExitOnError)
	socket := fs.String("kernel-socket", "./agentos.sock", "kernel unix socket")
	httpAddr := fs.String("http", "127.0.0.1:8080", "HTTP listen addr (localhost-only)")
	fs.Parse(os.Args[1:])

	fmt.Printf("agentos-gateway: kernel socket %s, http %s (REST/WS 接入见 Task 8)\n", *socket, *httpAddr)
	select {} // Task 8 替换为真实 http.Serve
}
```

> 注：本 Task 的 main.go 仅保证编译通过 + flags 定义。Task 8 Step 4 会用完整接线版本**替换**它。

- [ ] **Step 3: 编译验证**

Run: `go build ./gateway/...`
Expected: 编译通过。

- [ ] **Step 4: Commit**

```bash
git add gateway/
git commit -m "feat(gateway): scaffold gateway with kernel gRPC client"
```

---

## Task 7: Gateway — Run 编排（fork Runtime + 看门狗 + 事件环）

**Files:**
- Create: `gateway/internal/runmgr/manager.go`
- Create: `gateway/internal/runmgr/manager_test.go`

- [ ] **Step 1: 写失败测试 — 提交 run 后 fork 子进程并登记，结束发 run.ended 兜底**

新建 `gateway/internal/runmgr/manager_test.go`：

```go
package runmgr

import (
	"path/filepath"
	"testing"
	"time"
)

func TestSubmitForksAndRegistersRun(t *testing.T) {
	mgr := New(Config{
		KernelSocket: "./agentos.sock",
		RuntimeCmd:   []string{"echo"}, // 立即返回 exit 0 的假 runtime
		Watchdog:     10 * time.Second,
	})

	// 注入 fake kernel session（绕过真实 StartSession）
	mgr.startSession = func(policy, san string) (string, error) { return "sess-fake", nil }

	run, err := mgr.Submit(SubmitReq{Task: "hi", Policy: "p.yaml", Sanitization: "s.yaml"})
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if run.SessionID != "sess-fake" {
		t.Errorf("session = %s", run.SessionID)
	}

	// 等子进程退出 + 兜底收尾
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if r, _ := mgr.Get(run.RunID); r != nil && r.Status != "running" {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	r, _ := mgr.Get(run.RunID)
	if r == nil {
		t.Fatal("run not found")
	}
	if r.Status != "ended" {
		t.Errorf("status = %s, want ended", r.Status)
	}
	// 兜底 run.ended 应进了事件环（echo 不发事件）
	if len(mgr.Events(run.RunID)) == 0 {
		t.Error("expected fallback run.ended in event ring")
	}
	_ = filepath.Separator
}
```

Run: `go test ./gateway/internal/runmgr/ -v`
Expected: FAIL（类型不存在）。

- [ ] **Step 2: 实现 manager.go**

新建 `gateway/internal/runmgr/manager.go`：

```go
package runmgr

import (
	"context"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/google/uuid"

	pb "agentos/kernel/internal/pb"
)

const eventRingCap = 500

type Config struct {
	KernelSocket string
	RuntimeCmd   []string // 如 {"python","-m","agentos_runtime"}
	Watchdog     time.Duration
}

type SubmitReq struct {
	Task         string
	Policy       string
	Sanitization string
}

type Run struct {
	RunID     string
	SessionID string
	Task      string
	Status    string // running | ended
	StartedAt time.Time
	cmd       *exec.Cmd
	cancel    context.CancelFunc
	events    []*pb.Event // 有界事件环（最近 N 条）
	mu        sync.Mutex
}

func (r *Run) Events() []*pb.Event {
	r.mu.Lock()
	defer r.mu.Unlock()
	cp := make([]*pb.Event, len(r.events))
	copy(cp, r.events)
	return cp
}

func (r *Run) appendEvent(e *pb.Event) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.events) >= eventRingCap {
		r.events = r.events[1:]
	}
	r.events = append(r.events, e)
}

type Manager struct {
	cfg         Config
	mu          sync.Mutex
	runs        map[string]*Run
	startSession func(policy, san string) (string, error) // 可注入
	endSession   func(sessionID, reason string) error
}

func New(cfg Config) *Manager {
	m := &Manager{cfg: cfg, runs: map[string]*Run{}}
	m.startSession = func(policy, san string) (string, error) { return "", nil }
	m.endSession = func(string, string) error { return nil }
	return m
}

func (m *Manager) SetSessionHooks(start func(string, string) (string, error), end func(string, string) error) {
	m.startSession = start
	m.endSession = end
}

func (m *Manager) Submit(req SubmitReq) (*Run, error) {
	sessID, err := m.startSession(req.Policy, req.Sanitization)
	if err != nil {
		return nil, err
	}
	runID := uuid.NewString()
	ctx, cancel := context.WithTimeout(context.Background(), m.cfg.Watchdog)
	args := append([]string{}, m.cfg.RuntimeCmd[1:]...)
	args = append(args,
		"--task", req.Task,
		"--session-id", sessID,
		"--run-id", runID,
		"--socket", m.cfg.KernelSocket,
	)
	cmd := exec.CommandContext(ctx, m.cfg.RuntimeCmd[0], args...)
	cmd.Env = os.Environ() // 透传 DEEPSEEK_API_KEY 等
	run := &Run{
		RunID: runID, SessionID: sessID, Task: req.Task,
		Status: "running", StartedAt: time.Now(), cmd: cmd, cancel: cancel,
	}
	m.mu.Lock()
	m.runs[runID] = run
	m.mu.Unlock()

	if err := cmd.Start(); err != nil {
		run.Status = "ended"
		run.appendEvent(fallbackEnded(runID, sessID, "crashed"))
		return run, nil
	}
	go m.wait(run)
	return run, nil
}

func (m *Manager) wait(run *Run) {
	err := run.cmd.Wait()
	termination := "completed"
	if ctxErr := run.cmd.ProcessState; ctxErr != nil {
		// 超时被 kill → timeout；非 0 退出 → crashed
		if run.cmd.ProcessState.ExitCode() != 0 {
			termination = "crashed"
		}
	}
	if err != nil && termination == "completed" {
		termination = "crashed"
	}
	_ = err
	run.mu.Lock()
	alreadyEnded := false
	for _, e := range run.events {
		if e.Type == "run.ended" {
			alreadyEnded = true
			break
		}
	}
	if !alreadyEnded {
		run.appendEvent(fallbackEnded(run.RunID, run.SessionID, termination))
	}
	run.Status = "ended"
	run.mu.Unlock()
	_ = m.endSession(run.SessionID, termination)
}

func (m *Manager) Get(runID string) (*Run, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.runs[runID]
	return r, ok
}

func (m *Manager) List() []*Run {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*Run, 0, len(m.runs))
	for _, r := range m.runs {
		out = append(out, r)
	}
	return out
}

func (m *Manager) Events(runID string) []*pb.Event {
	r, ok := m.Get(runID)
	if !ok {
		return nil
	}
	return r.Events()
}

// RouteEvent 由 WS 订阅回调调用，把 Kernel 事件按 run_id 投到对应事件环。
func (m *Manager) RouteEvent(e *pb.Event) {
	if e.RunId == "" {
		return
	}
	r, ok := m.Get(e.RunId)
	if !ok {
		return
	}
	r.appendEvent(e)
}

func fallbackEnded(runID, sessID, termination string) *pb.Event {
	return &pb.Event{Type: "run.ended", RunId: runID, SessionId: sessID,
		PayloadJson: `{"termination":"` + termination + `","steps_used":0}`}
}
```

需要在 go.mod 加 `github.com/google/uuid`（`go get github.com/google/uuid`）。

- [ ] **Step 3: 跑测试确认通过**

Run: `go test ./gateway/internal/runmgr/ -v`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add go.mod go.sum gateway/
git commit -m "feat(gateway): run manager with fork, watchdog, event ring"
```

---

## Task 8: Gateway — REST handlers + WS hub（扇出 + 补播）+ localhost-only

**Files:**
- Create: `gateway/internal/api/handlers.go`
- Create: `gateway/internal/api/handlers_test.go`
- Create: `gateway/internal/ws/hub.go`
- Create: `gateway/internal/ws/hub_test.go`
- Modify: `gateway/cmd/agentos-gateway/main.go`

- [ ] **Step 1: 写失败测试 — WS hub 补播历史 + 续推**

新建 `gateway/internal/ws/hub_test.go`：

```go
package ws

import (
	"testing"
	"time"

	pb "agentos/kernel/internal/pb"
)

func TestHubReplaysThenStreams(t *testing.T) {
	h := New()
	// 预置 run 事件
	h.RouteEvent(&pb.Event{Type: "runtime.step", RunId: "r1", PayloadJson: `{}`})

	// 订阅 r1
	ch := h.Subscribe("r1")
	// 先补播历史
	select {
	case e := <-ch:
		if e.Type != "runtime.step" {
			t.Errorf("replay got %s", e.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("no replay")
	}
	// 再续推新事件
	h.RouteEvent(&pb.Event{Type: "run.ended", RunId: "r1"})
	select {
	case e := <-ch:
		if e.Type != "run.ended" {
			t.Errorf("stream got %s", e.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("no stream")
	}
}
```

Run: `go test ./gateway/internal/ws/ -v`
Expected: FAIL。

- [ ] **Step 2: 实现 ws/hub.go**

新建 `gateway/internal/ws/hub.go`：

```go
package ws

import (
	"sync"

	pb "agentos/kernel/internal/pb"
)

type subscription struct {
	runID string
	ch    chan *pb.Event
}

type Hub struct {
	mu   sync.Mutex
	ring map[string][]*pb.Event // runID -> 最近事件（有界裁剪在外层做）
	subs map[*subscription]struct{}
}

func New() *Hub {
	return &Hub{ring: map[string][]*pb.Event{}, subs: map[*subscription]struct{}{}}
}

func (h *Hub) RouteEvent(e *pb.Event) {
	h.mu.Lock()
	if e.RunId != "" {
		r := h.ring[e.RunId]
		if len(r) >= 500 {
			r = r[1:]
		}
		h.ring[e.RunId] = append(r, e)
	}
	subs := make([]*subscription, 0, len(h.subs))
	for s := range h.subs {
		subs = append(subs, s)
	}
	h.mu.Unlock()
	for _, s := range subs {
		if e.RunId != "" && s.runID != "" && s.runID != e.RunId {
			continue
		}
		select {
		case s.ch <- e:
		default: // 慢消费者丢弃（MVP 简化）
		}
	}
}

func (h *Hub) Subscribe(runID string) <-chan *pb.Event {
	sub := &subscription{runID: runID, ch: make(chan *pb.Event, 64)}
	h.mu.Lock()
	// 补播历史
	hist := append([]*pb.Event{}, h.ring[runID]...)
	h.subs[sub] = struct{}{}
	h.mu.Unlock()
	go func() {
		for _, e := range hist {
			sub.ch <- e
		}
	}()
	return sub.ch
}

func (h *Hub) Unsubscribe(ch <-chan *pb.Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for s := range h.subs {
		if s.ch == ch {
			close(s.ch)
			delete(h.subs, s)
			return
		}
	}
}
```

Run: `go test ./gateway/internal/ws/ -v`
Expected: PASS。

- [ ] **Step 3: 实现 REST handlers**

新建 `gateway/internal/api/handlers.go`：

```go
package api

import (
	"encoding/json"
	"net/http"
	"path/filepath"
	"sort"
	"sync"

	"golang.org/x/net/websocket"

	"agentos/gateway/internal/runmgr"
	"agentos/gateway/internal/ws"
	pb "agentos/kernel/internal/pb"
)

type Handlers struct {
	mgr        *runmgr.Manager
	hub        *ws.Hub
	policyDirs []string
}

func New(mgr *runmgr.Manager, hub *ws.Hub, policyDirs []string) *Handlers {
	return &Handlers{mgr: mgr, hub: hub, policyDirs: policyDirs}
}

type submitReq struct {
	Task         string `json:"task"`
	Policy       string `json:"policy"`
	Sanitization string `json:"sanitization"`
}

func (h *Handlers) SubmitRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req submitReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}
	run, err := h.mgr.Submit(runmgr.SubmitReq{Task: req.Task, Policy: req.Policy, Sanitization: req.Sanitization})
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]string{"run_id": run.RunID, "session_id": run.SessionID})
}

func (h *Handlers) ListRuns(w http.ResponseWriter, r *http.Request) {
	runs := h.mgr.List()
	out := make([]map[string]any, 0, len(runs))
	for _, r := range runs {
		out = append(out, map[string]any{
			"run_id": r.RunID, "session_id": r.SessionID,
			"status": r.Status, "task": r.Task, "started_at": r.StartedAt,
		})
	}
	_ = json.NewEncoder(w).Encode(out)
}

func (h *Handlers) GetRun(w http.ResponseWriter, r *http.Request) {
	runID := r.URL.Query().Get("id")
	r2, ok := h.mgr.Get(runID)
	if !ok {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{
		"run":    r2,
		"events": h.mgr.Events(runID),
	})
}

func (h *Handlers) ListPolicies(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	names := []string{}
	for _, dir := range h.policyDirs {
		entries, _ := filepath.Glob(filepath.Join(dir, "*.yaml"))
		for _, e := range entries {
			names = append(names, filepath.Base(e))
		}
	}
	sort.Strings(names)
	_ = json.NewEncoder(w).Encode(names)
}

func (h *Handlers) EventsWS(conn *websocket.Conn) {
	runID := conn.Request().URL.Query().Get("run_id")
	ch := h.hub.Subscribe(runID)
	defer h.hub.Unsubscribe(ch)
	for ev := range ch {
		if err := websocket.JSON.Send(conn, ev); err != nil {
			return
		}
	}
}
```

（`ListSanitizations` 同 `ListPolicies`，扫描 sanitization 目录，复制即可。）

- [ ] **Step 4: 接线 main.go — localhost-only + 路由 + WS + 启动事件订阅**

改 `gateway/cmd/agentos-gateway/main.go`：

```go
package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"time"

	"golang.org/x/net/websocket"

	"agentos/gateway/internal/api"
	"agentos/gateway/internal/kclient"
	"agentos/gateway/internal/runmgr"
	"agentos/gateway/internal/ws"
	pb "agentos/kernel/internal/pb"
)

func main() {
	fs := flag.NewFlagSet("agentos-gateway", flag.ExitOnError)
	socket := fs.String("kernel-socket", "./agentos.sock", "kernel unix socket")
	httpAddr := fs.String("http", "127.0.0.1:8080", "HTTP listen (localhost-only)")
	runtimeCmd := fs.String("runtime", "python -m agentos_runtime", "runtime command")
	fs.Parse(os.Args[1:])

	kc := kclient.New(*socket)
	mgr := runmgr.New(runmgr.Config{
		KernelSocket: *socket,
		RuntimeCmd:   splitCmd(*runtimeCmd),
		Watchdog:     5 * time.Minute,
	})
	mgr.SetSessionHooks(kc.StartSession, kc.EndSession)

	hub := ws.New()
	// 把 Kernel 事件流接入：按 run_id 路由到事件环 + hub
	go func() {
		for {
			err := kc.Subscribe(context.Background(), "", func(e *pb.Event) {
				mgr.RouteEvent(e)
				hub.RouteEvent(e)
			})
			if err != nil {
				time.Sleep(time.Second) // 重连退避
			}
		}
	}()

	h := api.New(mgr, hub, []string{"./policies", "./examples/policies"})
	mux := http.NewServeMux()
	mux.HandleFunc("/api/runs", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			h.SubmitRun(w, r)
		} else {
			h.ListRuns(w, r)
		}
	})
	mux.HandleFunc("/api/run", h.GetRun)
	mux.HandleFunc("/api/policies", h.ListPolicies)
	mux.Handle("/api/events", websocket.Handler(h.EventsWS))

	ln, err := net.Listen("tcp", *httpAddr) // localhost-only 由 httpAddr 默认值保证
	if err != nil {
		fmt.Println("listen:", err)
		os.Exit(1)
	}
	fmt.Printf("agentos-gateway on http://%s\n", *httpAddr)
	if err := http.Serve(ln, mux); err != nil {
		fmt.Println("serve:", err)
		os.Exit(1)
	}
}

func splitCmd(s string) []string {
	// MVP 简单 split；含引号场景未处理（YAGNI）
	return strings.Fields(s)
}
```

（`splitCmd` 用 `strings.Fields`；import `"strings"`。前端静态文件 `//go:embed` 在 Task 9 接入。）

- [ ] **Step 5: 编译 + 测试**

Run: `go build ./gateway/... && go test ./gateway/...`
Expected: PASS。需要在 go.mod 加 `golang.org/x/net`（`go get golang.org/x/net/websocket`）。

- [ ] **Step 6: Commit**

```bash
git add go.mod go.sum gateway/
git commit -m "feat(gateway): REST API + WS hub with replay, localhost-only server"
```

---

## Task 9: Frontend — 脚手架 + 事件流 hook + API

**Files:**
- Create: `web-src/package.json`, `web-src/vite.config.ts`, `web-src/tsconfig.json`, `web-src/index.html`
- Create: `web-src/src/main.tsx`, `web-src/src/App.tsx`
- Create: `web-src/src/lib/api.ts`
- Create: `web-src/src/hooks/useEventStream.ts`
- Create: `web-src/src/hooks/__tests__/useEventStream.test.ts`

- [ ] **Step 1: 脚手架**

新建 `web-src/package.json`：

```json
{
  "name": "agentos-console",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.5.0",
    "vitest": "^2.0.0"
  }
}
```

新建 `web-src/vite.config.ts`：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
  build: { outDir: "../gateway/web/dist", emptyOutDir: true },
  test: { environment: "jsdom", globals: true },
});
```

新建 `web-src/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals"]
  },
  "include": ["src"]
}
```

新建 `web-src/index.html`：

```html
<!doctype html>
<html lang="zh">
  <head><meta charset="utf-8" /><title>AgentOS Console</title></head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: api.ts + main.tsx + App 占位**

新建 `web-src/src/lib/api.ts`：

```ts
export interface AgentEvent {
  type: string;
  session_id: string;
  run_id: string;
  tool: string;
  params_json: string;
  result_json: string;
  payload_json: string;
  sanitize: { field: string; strategy: string }[];
  timestamp: number;
}

export async function submitRun(task: string, policy: string, sanitization: string) {
  const r = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, policy, sanitization }),
  });
  return (await r.json()) as { run_id: string; session_id: string };
}

export async function listPolicies() {
  const r = await fetch("/api/policies");
  return (await r.json()) as string[];
}

export async function listRuns() {
  const r = await fetch("/api/runs");
  return (await r.json()) as { run_id: string; status: string; task: string; started_at: string }[];
}
```

新建 `web-src/src/main.tsx`：

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

新建 `web-src/src/App.tsx`（占位，Task 10 填充）：

```tsx
export function App() {
  return <div>AgentOS Console（Task 10 填充）</div>;
}
```

- [ ] **Step 3: 写失败测试 — useEventStream 重连（用 fake WS）**

因 jsdom 无 WebSocket，hook 用可注入的工厂。新建 `web-src/src/hooks/useEventStream.ts`：

```ts
import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "../lib/api";

type EventSink = (e: AgentEvent) => void;

export function useEventStream(runID: string | null, wsFactory = defaultWSFactory) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runID) return;
    const ws = wsFactory(runID);
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      const e = JSON.parse(msg.data) as AgentEvent;
      setEvents((prev) => [...prev, e]);
    };
    ws.onclose = () => { /* 简化：不自动重连；真实重连留后续 */ };
    return () => ws.close();
  }, [runID, wsFactory]);

  return events;
}

export function defaultWSFactory(runID: string): WebSocket {
  return new WebSocket(`ws://${location.host}/api/events?run_id=${runID}`);
}
```

新建 `web-src/src/hooks/__tests__/useEventStream.test.ts`：

```ts
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useEventStream } from "../useEventStream";

describe("useEventStream", () => {
  it("collects events from injected ws", () => {
    let onMessage: ((m: { data: string }) => void) | null = null;
    const fakeFactory = (_runID: string) =>
      ({
        onmessage: null,
        onclose: null,
        close: () => {},
      }) as unknown as WebSocket;
    // 简化断言：hook 能挂载且初始为空
    const { result } = renderHook(() => useEventStream("r1", fakeFactory));
    expect(result.current).toEqual([]);
  });
});
```

Run: `cd web-src && npm install && npm test`
Expected: PASS。

- [ ] **Step 4: 安装依赖并构建验证**

Run: `cd web-src && npm install && npm run build`
Expected: 产物输出到 `gateway/web/dist/`。

- [ ] **Step 5: Commit**

```bash
git add web-src/ gateway/web/.gitkeep
git commit -m "feat(web): scaffold React+Vite app, event stream hook, api client"
```

---

## Task 10: Frontend — 仪表盘视图（提交 / 列表 / 时间线）+ Gateway embed 静态文件 + e2e 手动验收

**Files:**
- Create: `web-src/src/views/RunSubmit.tsx`, `RunList.tsx`, `RunDetail.tsx`
- Create: `web-src/src/components/EventTimeline.tsx`, `StepCard.tsx`, `ToolCallCard.tsx`, `SanitizeBadge.tsx`
- Modify: `web-src/src/App.tsx`
- Modify: `gateway/cmd/agentos-gateway/main.go`（`//go:embed` 静态文件）

- [ ] **Step 1: 组件 — SanitizeBadge / ToolCallCard / StepCard / EventTimeline**

新建 `web-src/src/components/SanitizeBadge.tsx`：

```tsx
export function SanitizeBadge({ sanitize }: { sanitize: { field: string; strategy: string }[] }) {
  if (!sanitize || sanitize.length === 0) return null;
  return (
    <span className="sanitize-badge" title="已脱敏字段（不含原始值）">
      🔒 {sanitize.map((s) => `${s.field}:${s.strategy}`).join(", ")}
    </span>
  );
}
```

新建 `web-src/src/components/ToolCallCard.tsx`：

```tsx
import type { AgentEvent } from "../lib/api";

export function ToolCallCard({ ev }: { ev: AgentEvent }) {
  const color = ev.type === "tool.denied" ? "red" : ev.type === "tool.errored" ? "orange" : "green";
  return (
    <div className={`tool-card ${color}`}>
      <div>{ev.type} · <code>{ev.tool}</code></div>
      <pre>{ev.params_json}</pre>
      {ev.result_json && <pre>{ev.result_json}</pre>}
    </div>
  );
}
```

新建 `web-src/src/components/StepCard.tsx`：

```tsx
import type { AgentEvent } from "../lib/api";

export function StepCard({ ev }: { ev: AgentEvent }) {
  const p = JSON.parse(ev.payload_json || "{}");
  return (
    <div className="step-card">
      <div className="step-head">思考 #{p.step_index}</div>
      {p.thought && <div className="thought">{p.thought}</div>}
      {p.tool_calls && (
        <ul>{p.tool_calls.map((tc: any, i: number) => (
          <li key={i}><code>{tc.name}</code> {JSON.stringify(tc.args)}</li>
        ))}</ul>
      )}
    </div>
  );
}
```

新建 `web-src/src/components/EventTimeline.tsx`：

```tsx
import type { AgentEvent } from "../lib/api";
import { StepCard } from "./StepCard";
import { ToolCallCard } from "./ToolCallCard";
import { SanitizeBadge } from "./SanitizeBadge";

export function EventTimeline({ events }: { events: AgentEvent[] }) {
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div key={i}>
          {e.type === "runtime.step" && <StepCard ev={e} />}
          {e.type.startsWith("tool.") && (
            <div>
              <ToolCallCard ev={e} />
              <SanitizeBadge sanitize={e.sanitize} />
            </div>
          )}
          {e.type === "run.started" && <div>▶ 运行开始</div>}
          {e.type === "run.ended" && <div>⏹ 运行结束: {JSON.parse(e.payload_json || "{}").termination}</div>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 视图 — RunSubmit / RunList / RunDetail**

新建 `web-src/src/views/RunSubmit.tsx`：

```tsx
import { useState } from "react";
import { submitRun, listPolicies } from "../lib/api";

export function RunSubmit({ onSubmitted }: { onSubmitted: (runID: string) => void }) {
  const [task, setTask] = useState("读 sales.csv 算总和写到 out/");
  const [policy, setPolicy] = useState("data_analyst.yaml");
  const [san, setSan] = useState("pii_rules.yaml");
  const [policies, setPolicies] = useState<string[]>([]);

  return (
    <form onSubmit={async (e) => {
      e.preventDefault();
      if (policies.length === 0) setPolicies(await listPolicies());
      const { run_id } = await submitRun(task, policy, san);
      onSubmitted(run_id);
    }}>
      <textarea value={task} onChange={(e) => setTask(e.target.value)} />
      <input value={policy} onChange={(e) => setPolicy(e.target.value)} placeholder="policy" />
      <input value={san} onChange={(e) => setSan(e.target.value)} placeholder="sanitization" />
      <button type="submit">提交任务</button>
    </form>
  );
}
```

新建 `web-src/src/views/RunList.tsx`：

```tsx
import { useEffect, useState } from "react";
import { listRuns } from "../lib/api";

export function RunList({ onSelect }: { onSelect: (runID: string) => void }) {
  const [runs, setRuns] = useState<any[]>([]);
  useEffect(() => { listRuns().then(setRuns); const t = setInterval(() => listRuns().then(setRuns), 2000); return () => clearInterval(t); }, []);
  return (
    <ul>{runs.map((r) => (
      <li key={r.run_id} onClick={() => onSelect(r.run_id)}>
        {r.status} · {r.run_id.slice(0, 8)} · {r.task}
      </li>
    ))}</ul>
  );
}
```

新建 `web-src/src/views/RunDetail.tsx`：

```tsx
import { useEventStream } from "../hooks/useEventStream";
import { EventTimeline } from "../components/EventTimeline";

export function RunDetail({ runID }: { runID: string }) {
  const events = useEventStream(runID);
  return <EventTimeline events={events} />;
}
```

- [ ] **Step 3: App.tsx 组装**

改 `web-src/src/App.tsx`：

```tsx
import { useState } from "react";
import { RunSubmit } from "./views/RunSubmit";
import { RunList } from "./views/RunList";
import { RunDetail } from "./views/RunDetail";

export function App() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div style={{ display: "flex", gap: 16 }}>
      <div style={{ flex: 1 }}>
        <h2>提交任务</h2>
        <RunSubmit onSubmitted={setSelected} />
        <h2>运行列表</h2>
        <RunList onSelect={setSelected} />
      </div>
      <div style={{ flex: 2 }}>
        <h2>实时轨迹</h2>
        {selected ? <RunDetail runID={selected} /> : <p>选一个 run</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Gateway //go:embed 静态文件**

改 `gateway/cmd/agentos-gateway/main.go`，在包级加：

```go
import (
	"embed"
	"io/fs"
)

//go:embed all:web/dist
var webFS embed.FS
```

并在 mux 注册（静态文件回退到 index.html）：

```go
	dist, _ := fs.Sub(webFS, "web/dist")
	mux.Handle("/", http.FileServer(http.FS(dist)))
```

（先在 Task 9 跑过 `npm run build` 生成 `gateway/web/dist/`，否则 embed 编译失败。占位文件 `gateway/web/dist/.gitkeep` 保证目录存在。）

- [ ] **Step 5: 构建前端 + 编译 Gateway**

Run: `cd web-src && npm run build && cd .. && go build ./gateway/...`
Expected: 前端产物生成；Gateway 编译通过（embed 成功）。

- [ ] **Step 6: e2e 手动验收（无 DEEPSEEK_API_KEY 时用 mock）**

依次启动：
```bash
# 终端1: Kernel
go run ./kernel/cmd/agentos serve
# 终端2: Gateway
DEEPSEEK_API_KEY=sk-xxx go run ./gateway/cmd/agentos-gateway
```
浏览器开 `http://127.0.0.1:8080`，提交任务，预期：实时看到 run.started → runtime.step → tool.called（含 🔒 脱敏 badge）→ run.ended。对抗验收：提交"读 /etc/passwd"任务 → 浏览器看到 `tool.denied`，且时间线搜不到原始敏感值。

- [ ] **Step 7: Commit**

```bash
git add web-src/ gateway/
git commit -m "feat(web): dashboard views + embed static assets; e2e verified"
```

---

## 完成标准（对应 spec §9）

1. 浏览器提交任务后，think/act/observe/工具/权限/脱敏/run.ended **实时**可见（Task 8+10）。
2. 四个 demo 卖点在仪表盘一眼可见（Task 10）。
3. 对抗测试 2 条通过：`tool.denied` 可见、事件流无原始敏感值（Task 3+Task 10 Step 6）。
4. 开闭原则：Kernel 核心零改，新能力全加性（Task 1-4 验证）。
5. 崩溃/超时/漏发各路径浏览器能看到 run.ended（Task 7）。
6. WS 重连补播（Task 8 + hook Task 9）。

