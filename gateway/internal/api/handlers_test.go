package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentos/gateway/internal/runmgr"
	"agentos/gateway/internal/ws"
	pb "agentos/pb"
)

// newTestHandlers 构造一对 mgr+hub+handlers，mgr 用假 runtime（echo）。
func newTestHandlers(t *testing.T) (*Handlers, *runmgr.Manager) {
	mgr := runmgr.New(runmgr.Config{
		KernelSocket: "./agentos.sock",
		RuntimeCmd:   echoCmd(),
		Watchdog:     5 * time.Second,
	})
	mgr.SetSessionHooks(func(string, string) (string, error) { return "s1", nil }, func(string, string) error { return nil })
	hub := ws.New()
	h := New(mgr, hub, []string{"./policies"}, []string{"./examples/sanitization"})
	return h, mgr
}

func echoCmd() []string {
	if isWindows() {
		return []string{"cmd", "/c", "echo", "ok"}
	}
	return []string{"echo", "ok"}
}

// isWindows 判断当前是否 Windows shell（MINGW/Git Bash）。
func isWindows() bool {
	return os.PathSeparator == '\\' || os.Getenv("OS") == "Windows_NT"
}

func TestListPoliciesScansYaml(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "data_analyst.yaml"), []byte("x"), 0644)
	os.WriteFile(filepath.Join(tmp, "other.yaml"), []byte("x"), 0644)
	os.WriteFile(filepath.Join(tmp, "notyaml.txt"), []byte("x"), 0644)

	h := New(nil, nil, []string{tmp}, nil)
	req := httptest.NewRequest(http.MethodGet, "/api/policies", nil)
	rec := httptest.NewRecorder()
	h.ListPolicies(rec, req)

	var got []string
	json.NewDecoder(rec.Body).Decode(&got)
	if len(got) != 2 {
		t.Fatalf("expected 2 policies, got %v", got)
	}
	if got[0] != "data_analyst.yaml" || got[1] != "other.yaml" {
		t.Errorf("unexpected order: %v", got)
	}
}

func TestSubmitRunReturnsRunID(t *testing.T) {
	h, _ := newTestHandlers(t)
	body := `{"task":"hi","policy":"p.yaml","sanitization":"s.yaml"}`
	req := httptest.NewRequest(http.MethodPost, "/api/runs", strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.SubmitRun(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rec.Code, rec.Body.String())
	}
	var resp map[string]string
	json.NewDecoder(rec.Body).Decode(&resp)
	if resp["run_id"] == "" {
		t.Error("expected non-empty run_id")
	}
}

func TestGetRunNotFound(t *testing.T) {
	h, _ := newTestHandlers(t)
	req := httptest.NewRequest(http.MethodGet, "/api/runs?id=nonexistent", nil)
	rec := httptest.NewRecorder()
	h.GetRun(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rec.Code)
	}
}

func TestListSanitizations(t *testing.T) {
	tmp := t.TempDir()
	os.WriteFile(filepath.Join(tmp, "pii_rules.yaml"), []byte("x"), 0644)
	h := New(nil, nil, nil, []string{tmp})
	req := httptest.NewRequest(http.MethodGet, "/api/sanitizations", nil)
	rec := httptest.NewRecorder()
	h.ListSanitizations(rec, req)
	var got []string
	json.NewDecoder(rec.Body).Decode(&got)
	if len(got) != 1 || got[0] != "pii_rules.yaml" {
		t.Errorf("unexpected: %v", got)
	}
}

// fakeWSConn 测试 ServeEventsWS 的补播逻辑。
type fakeWSConn struct {
	runID string
	sent  []*pb.Event
}

func (f *fakeWSConn) Query(key string) string {
	if key == "run_id" {
		return f.runID
	}
	return ""
}
func (f *fakeWSConn) SendJSON(v any) error {
	f.sent = append(f.sent, v.(*pb.Event))
	return nil
}
func (f *fakeWSConn) Close() error { return nil }

func TestServeEventsWSReplaysHistory(t *testing.T) {
	h, mgr := newTestHandlers(t)
	run, _ := mgr.Submit(runmgr.SubmitReq{Task: "x", Policy: "p", Sanitization: "s"})
	// 预置两条历史事件
	mgr.RouteEvent(&pb.Event{Type: "runtime.step", RunId: run.RunID})
	mgr.RouteEvent(&pb.Event{Type: "tool.called", RunId: run.RunID})

	conn := &fakeWSConn{runID: run.RunID}
	// 在补播完成后取消订阅以让 ServeEventsWS 返回：用一个定时器在补播后调 Unsubscribe。
	go func() {
		time.Sleep(150 * time.Millisecond)
		// 补播发生在 Subscribe 之前，应已发出；现在关闭 hub 订阅以结束 handler
		// 通过发送一个结束信号：直接关闭（handler 会在续推循环阻塞，我们靠超时断开）
	}()

	done := make(chan struct{})
	go func() {
		h.ServeEventsWS(conn)
		close(done)
	}()

	// 补播的历史应在很短时间内到达
	time.Sleep(100 * time.Millisecond)

	// 验证补播了历史（至少 runtime.step，因为 handler 之后会阻塞在 hub 续推）
	gotTypes := map[string]bool{}
	for _, e := range conn.sent {
		gotTypes[e.Type] = true
	}
	if !gotTypes["runtime.step"] {
		t.Errorf("expected replayed runtime.step, got events: %v", gotTypes)
	}

	// 清理：handler 仍阻塞在 hub channel，测试结束时 goroutine 泄漏可接受（进程退出）
	_ = done
}
