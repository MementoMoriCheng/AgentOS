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

// Server 是 gRPC 服务端，把所有内核部件接起来。
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
	globalBus *eventbus.InProcess // 所有 session + Runtime 事件汇于此，供 SubscribeEvents 订阅
}

// New 创建一个 Server，注册内置 fs 工具。
func New(auditDir string) *Server {
	reg := tools.NewRegistry()
	reg.Register(tools.FSReadTool{})
	reg.Register(tools.FSWriteTool{})
	reg.Register(tools.FSListTool{})
	return &Server{
		sessions:  map[string]*session.Session{},
		pipelines: map[string]*pipeline.Pipeline{},
		registry:  reg,
		scheduler: scheduler.New(4), // MVP 并发上限 4
		auth:      auth.LocalAuthenticator{},
		auditDir:  auditDir,
		globalBus: eventbus.NewInProcess(),
	}
}

// StartSession 加载 Policy（含白名单校验）+ Sanitizer，建 Session + Pipeline + EventBus + 审计订阅。
func (s *Server) StartSession(ctx context.Context, req *pb.StartSessionRequest) (*pb.StartSessionResponse, error) {
	// Kernel 认证第二层：Policy 路径白名单。允许 ./policies 或 ./examples/policies。
	if !auth.IsTrustedPolicy(req.PolicyPath, "./policies") &&
		!auth.IsTrustedPolicy(req.PolicyPath, "./examples/policies") {
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

	// 所有 session 共享 globalBus（事件用 SessionID 区分）；审计订阅注册到 globalBus。
	audit.RegisterAuditSubscriber(ledger, s.globalBus)

	identity, _ := s.auth.Authenticate(ctx)

	sess := &session.Session{
		ID:        id,
		Identity:  identity.User,
		Policy:    pol,
		Gate:      policy.NewGate(pol),
		Sanitizer: san,
		Account: session.NewAccount(session.ResourceQuota{
			MaxSteps:  pol.MaxSteps,
			MaxTokens: pol.MaxTokens,
		}),
		Ledger: ledger,
	}
	pipe := pipeline.New(s.registry, s.globalBus)

	s.mu.Lock()
	s.sessions[id] = sess
	s.pipelines[id] = pipe
	s.mu.Unlock()

	s.globalBus.Publish(eventbus.Event{
		Type: "session.started", SessionID: id, Identity: identity.User,
	})

	return &pb.StartSessionResponse{SessionId: id}, nil
}

// CallTool 通过 Scheduler 占并发槽后调 Pipeline。
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

// EndSession 结束会话：从注册表移除，发布 session.ended 事件。
// 由网关在 run 结束时调用。
func (s *Server) EndSession(ctx context.Context, req *pb.EndSessionRequest) (*pb.EndSessionResponse, error) {
	s.mu.Lock()
	delete(s.sessions, req.SessionId)
	delete(s.pipelines, req.SessionId)
	s.mu.Unlock()

	s.globalBus.Publish(eventbus.Event{
		Type:      "session.ended",
		SessionID: req.SessionId,
		Payload:   map[string]any{"reason": req.Reason},
	})
	return &pb.EndSessionResponse{}, nil
}

// SubscribeEvents 把全局总线事件 stream 给调用方（网关）。
// 可按 session_id 过滤；为空则全收。
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

// EmitRuntimeEvent 把 Runtime 事件灌进全局总线（事件枢纽统一在 Kernel）。
func (s *Server) EmitRuntimeEvent(ctx context.Context, e *pb.Event) (*pb.EmitResponse, error) {
	s.globalBus.Publish(fromProtoEvent(e))
	return &pb.EmitResponse{}, nil
}

// toProtoEvent 把内部事件转成 protobuf 信封（含脱敏摘要，无原始值）。
func toProtoEvent(e eventbus.Event) *pb.Event {
	params, _ := json.Marshal(e.Params)
	result, _ := json.Marshal(e.Result)
	payload, _ := json.Marshal(e.Payload)
	var san []*pb.FieldSanitization
	for _, f := range e.Sanitize {
		san = append(san, &pb.FieldSanitization{Field: f.Field, Strategy: f.Strategy})
	}
	return &pb.Event{
		Type:        e.Type,
		SessionId:   e.SessionID,
		RunId:       e.RunID,
		Tool:        e.Tool,
		ParamsJson:  string(params),
		ResultJson:  string(result),
		Identity:    e.Identity,
		Sanitize:    san,
		PayloadJson: string(payload),
		Timestamp:   e.Timestamp,
	}
}

// fromProtoEvent 把 protobuf 事件转回内部事件（用于 Runtime 灌入的事件）。
func fromProtoEvent(e *pb.Event) eventbus.Event {
	var params, result, payload map[string]any
	if e.ParamsJson != "" {
		_ = json.Unmarshal([]byte(e.ParamsJson), &params)
	}
	if e.ResultJson != "" {
		_ = json.Unmarshal([]byte(e.ResultJson), &result)
	}
	if e.PayloadJson != "" {
		_ = json.Unmarshal([]byte(e.PayloadJson), &payload)
	}
	var san []eventbus.FieldSanitization
	for _, f := range e.Sanitize {
		san = append(san, eventbus.FieldSanitization{Field: f.Field, Strategy: f.Strategy})
	}
	return eventbus.Event{
		Type:      e.Type,
		SessionID: e.SessionId,
		RunID:     e.RunId,
		Tool:      e.Tool,
		Params:    params,
		Result:    result,
		Identity:  e.Identity,
		Sanitize:  san,
		Payload:   payload,
		Timestamp: e.Timestamp,
	}
}
