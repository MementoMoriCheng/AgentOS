package runmgr

import (
	"runtime"
	"testing"
	"time"

	pb "agentos/pb"
)

func TestSubmitForksAndRegistersRun(t *testing.T) {
	// 用 echo 立即返回 exit 0 的假 runtime。
	// Windows 上 echo 是 cmd 内建，需经 cmd /c；Unix 直接用 echo。
	runtimeCmd := []string{"echo", "hello"}
	if runtime.GOOS == "windows" {
		runtimeCmd = []string{"cmd", "/c", "echo", "hello"}
	}
	mgr := New(Config{
		KernelSocket: "./agentos.sock",
		RuntimeCmd:   runtimeCmd,
		Watchdog:     10 * time.Second,
	})
	mgr.start = func(policy, san string) (string, error) { return "sess-fake", nil }

	run, err := mgr.Submit(SubmitReq{Task: "hi", Policy: "p.yaml", Sanitization: "s.yaml"})
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if run.SessionID != "sess-fake" {
		t.Errorf("session = %s, want sess-fake", run.SessionID)
	}
	if run.RunID == "" {
		t.Error("run id should be non-empty")
	}

	// 等子进程退出 + 兜底收尾
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		r, _ := mgr.Get(run.RunID)
		if r != nil && r.Status != "running" {
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
	// echo 不发事件，应触发兜底 run.ended
	events := mgr.Events(run.RunID)
	if len(events) == 0 {
		t.Fatal("expected fallback run.ended in event ring")
	}
	last := events[len(events)-1]
	if last.Type != "run.ended" {
		t.Errorf("last event = %s, want run.ended", last.Type)
	}
	// echo 正常退出 → termination completed
	if last.PayloadJson != `{"termination":"completed","steps_used":0}` {
		t.Errorf("payload = %s", last.PayloadJson)
	}
}

func TestSubmitFailureProducesCrashedFallback(t *testing.T) {
	// 不存在的 runtime 命令 → Start 失败 → crashed 兜底
	mgr := New(Config{
		KernelSocket: "./agentos.sock",
		RuntimeCmd:   []string{"/nonexistent/binary-xyz"},
		Watchdog:     5 * time.Second,
	})
	mgr.start = func(policy, san string) (string, error) { return "s1", nil }

	run, err := mgr.Submit(SubmitReq{Task: "x"})
	if err != nil {
		t.Fatalf("Submit should not error on start failure: %v", err)
	}
	// Start 失败时同步设置 ended + crashed
	if run.Status != "ended" {
		t.Errorf("status = %s, want ended on start failure", run.Status)
	}
	events := mgr.Events(run.RunID)
	if len(events) != 1 || events[0].Type != "run.ended" {
		t.Fatalf("expected one crashed run.ended, got %+v", events)
	}
	if events[0].PayloadJson != `{"termination":"crashed","steps_used":0}` {
		t.Errorf("crashed payload wrong: %s", events[0].PayloadJson)
	}
}

func TestRouteEventAppendsToRunRing(t *testing.T) {
	mgr := New(Config{RuntimeCmd: []string{"echo"}, Watchdog: 5 * time.Second})
	mgr.start = func(string, string) (string, error) { return "s1", nil }
	run, _ := mgr.Submit(SubmitReq{Task: "x"})

	// 模拟 Runtime 发的事件
	mgr.RouteEvent(fakeEvent("runtime.step", run.RunID))
	mgr.RouteEvent(fakeEvent("tool.called", run.RunID))
	events := mgr.Events(run.RunID)
	// 至少这两条（可能还有兜底 run.ended，取决于 echo 是否已退出）
	gotTypes := map[string]bool{}
	for _, e := range events {
		gotTypes[e.Type] = true
	}
	if !gotTypes["runtime.step"] || !gotTypes["tool.called"] {
		t.Errorf("expected runtime.step and tool.called in ring, got %v", gotTypes)
	}
}

func TestRouteEventIgnoresEmptyRunID(t *testing.T) {
	mgr := New(Config{RuntimeCmd: []string{"echo"}, Watchdog: 5 * time.Second})
	// 事件无 run_id → 不应 panic，也不投递
	mgr.RouteEvent(fakeEvent("session.started", ""))
	// 无 run 注册，纯验证不 panic
}

func TestEventRingCapsAtCapacity(t *testing.T) {
	r := &Run{RunID: "r1"}
	for i := 0; i < eventRingCap+50; i++ {
		r.appendEvent(fakeEvent("runtime.step", "r1"))
	}
	got := r.Events()
	if len(got) > eventRingCap {
		t.Errorf("ring size = %d, should be capped at %d", len(got), eventRingCap)
	}
	if len(got) != eventRingCap {
		t.Errorf("ring size = %d, want exactly %d after overflow", len(got), eventRingCap)
	}
}

// fakeEvent 构造一个简单事件用于测试。
func fakeEvent(etype, runID string) *pb.Event {
	e := &pb.Event{Type: etype}
	if runID != "" {
		e.RunId = runID
	}
	return e
}
