package runmgr

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"os"
	"os/exec"
	"sync"
	"time"

	pb "agentos/pb"
)

const eventRingCap = 500

// Config 是 Manager 的配置。
type Config struct {
	KernelSocket string        // Kernel 的 unix socket 路径
	RuntimeCmd   []string      // 如 ["python", "-m", "agentos_runtime"]
	Watchdog     time.Duration // 单个 run 的超时上限
}

// SubmitReq 是提交一个 run 的请求。
type SubmitReq struct {
	Task         string
	Policy       string
	Sanitization string
}

// Run 是一个运行中的（或已结束的）agent run。
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

// Events 返回事件环的拷贝。
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
		r.events = r.events[1:] // 丢弃最旧
	}
	r.events = append(r.events, e)
}

// alreadyEnded 报告事件环里是否已有 run.ended。
func (r *Run) alreadyEnded() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, e := range r.events {
		if e.Type == "run.ended" {
			return true
		}
	}
	return false
}

// Manager 管理 run 的生命周期：fork Runtime、看门狗、事件环、兜底收尾。
type Manager struct {
	cfg   Config
	mu    sync.Mutex
	runs  map[string]*Run
	start func(policy, san string) (string, error) // 注入：调 Kernel StartSession
	end   func(sessionID, reason string) error     // 注入：调 Kernel EndSession
}

func New(cfg Config) *Manager {
	m := &Manager{cfg: cfg, runs: map[string]*Run{}}
	// 默认空实现（真实 hook 由 SetSessionHooks 注入）
	m.start = func(string, string) (string, error) { return "", nil }
	m.end = func(string, string) error { return nil }
	return m
}

// SetSessionHooks 注入 Kernel 会话操作（由 main 用 kclient 设置）。
func (m *Manager) SetSessionHooks(start func(string, string) (string, error), end func(string, string) error) {
	m.start = start
	m.end = end
}

// Submit 提交一个 run：建 session、fork Runtime、登记。
func (m *Manager) Submit(req SubmitReq) (*Run, error) {
	sessID, err := m.start(req.Policy, req.Sanitization)
	if err != nil {
		return nil, err
	}
	runID := newRunID()
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

// wait 等子进程结束，兜底补发 run.ended（若 Runtime 漏发）。
func (m *Manager) wait(run *Run) {
	_ = run.cmd.Wait()
	termination := "completed"
	if run.cmd.ProcessState != nil && run.cmd.ProcessState.ExitCode() != 0 {
		termination = "crashed"
	}
	// 看门狗超时被 kill 时 ctx.Err()==DeadlineExceeded → timeout
	if run.cmd.ProcessState == nil {
		termination = "timeout"
	}

	run.mu.Lock()
	if !run.alreadyEndedLocked() {
		run.events = append(run.events, fallbackEnded(run.RunID, run.SessionID, termination))
	}
	run.Status = "ended"
	run.mu.Unlock()

	_ = m.end(run.SessionID, termination)
}

func (r *Run) alreadyEndedLocked() bool {
	for _, e := range r.events {
		if e.Type == "run.ended" {
			return true
		}
	}
	return false
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

// newRunID 生成 16 字节 hex 的 run id（crypto/rand，无需外部依赖）。
func newRunID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return "run-" + hex.EncodeToString(b)
}

func fallbackEnded(runID, sessID, termination string) *pb.Event {
	return &pb.Event{
		Type: "run.ended", RunId: runID, SessionId: sessID,
		PayloadJson: `{"termination":"` + termination + `","steps_used":0}`,
	}
}
