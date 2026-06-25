package api

import (
	"encoding/json"
	"net/http"
	"path/filepath"
	"sort"

	"agentos/gateway/internal/runmgr"
	"agentos/gateway/internal/ws"
	pb "agentos/pb"
)

// Handlers 是网关的 REST handler 集合。
type Handlers struct {
	mgr           *runmgr.Manager
	hub           *ws.Hub
	policyDirs    []string
	sanitizationDirs []string
}

func New(mgr *runmgr.Manager, hub *ws.Hub, policyDirs, sanitizationDirs []string) *Handlers {
	return &Handlers{mgr: mgr, hub: hub, policyDirs: policyDirs, sanitizationDirs: sanitizationDirs}
}

type submitReq struct {
	Task         string `json:"task"`
	Policy       string `json:"policy"`
	Sanitization string `json:"sanitization"`
}

// SubmitRun 处理 POST /api/runs。
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
	writeJSON(w, http.StatusOK, map[string]string{"run_id": run.RunID, "session_id": run.SessionID})
}

// ListRuns 处理 GET /api/runs。
func (h *Handlers) ListRuns(w http.ResponseWriter, r *http.Request) {
	runs := h.mgr.List()
	out := make([]map[string]any, 0, len(runs))
	for _, r := range runs {
		out = append(out, map[string]any{
			"run_id":     r.RunID,
			"session_id": r.SessionID,
			"status":     r.Status,
			"task":       r.Task,
			"started_at": r.StartedAt,
		})
	}
	writeJSON(w, http.StatusOK, out)
}

// GetRun 处理 GET /api/runs/:id（query 参数 id）。
func (h *Handlers) GetRun(w http.ResponseWriter, r *http.Request) {
	runID := r.URL.Query().Get("id")
	r2, ok := h.mgr.Get(runID)
	if !ok {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"run": map[string]any{
			"run_id":     r2.RunID,
			"session_id": r2.SessionID,
			"status":     r2.Status,
			"task":       r2.Task,
			"started_at": r2.StartedAt,
		},
		"events": h.mgr.Events(runID),
	})
}

// ListPolicies 处理 GET /api/policies。
func (h *Handlers) ListPolicies(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, scanYaml(h.policyDirs))
}

// ListSanitizations 处理 GET /api/sanitizations。
func (h *Handlers) ListSanitizations(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, scanYaml(h.sanitizationDirs))
}

// ServeEventsWS 处理 WS /api/events?run_id=X。
// 补播历史（来自 runmgr 事件环）→ 订阅 hub 续推。
func (h *Handlers) ServeEventsWS(conn WSConn) {
	defer conn.Close()
	runID := conn.Query("run_id")

	// 先补播历史
	if runID != "" {
		r, ok := h.mgr.Get(runID)
		if ok {
			for _, e := range r.Events() {
				if err := conn.SendJSON(e); err != nil {
					return
				}
			}
		}
	}

	// 订阅 hub 续推
	ch := h.hub.Subscribe(runID)
	defer h.hub.Unsubscribe(ch)
	for ev := range ch {
		if err := conn.SendJSON(ev); err != nil {
			return
		}
	}
}

// scanYaml 扫描目录下的 *.yaml，返回去重的文件名列表。
func scanYaml(dirs []string) []string {
	seen := map[string]struct{}{}
	var names []string
	for _, dir := range dirs {
		entries, _ := filepath.Glob(filepath.Join(dir, "*.yaml"))
		for _, e := range entries {
			name := filepath.Base(e)
			if _, ok := seen[name]; !ok {
				seen[name] = struct{}{}
				names = append(names, name)
			}
		}
	}
	sort.Strings(names)
	return names
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// WSConn 抽象 WebSocket 连接，便于测试 handler 逻辑而不依赖具体 WS 库。
type WSConn interface {
	Query(key string) string
	SendJSON(v any) error
	Close() error
}

// 确保编译时 pb 被引用（payload 里用到）。
var _ = pb.Event{}
