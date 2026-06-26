package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"golang.org/x/net/websocket"

	"agentos/gateway/internal/api"
	"agentos/gateway/internal/kclient"
	"agentos/gateway/internal/runmgr"
	"agentos/gateway/web"
	"agentos/gateway/internal/ws"
	pb "agentos/pb"
)

func main() {
	flags := flag.NewFlagSet("agentos-gateway", flag.ExitOnError)
	socket := flags.String("kernel-socket", "./agentos.sock", "kernel unix socket")
	httpAddr := flags.String("http", "127.0.0.1:8080", "HTTP listen addr (localhost-only)")
	runtimeCmd := flags.String("runtime", "python -m agentos_runtime", "runtime command")
	watchdog := flags.Duration("watchdog", 5*time.Minute, "per-run timeout")
	flags.Parse(os.Args[1:])

	// 安全：强制 localhost-only。若 httpAddr 不是 loopback，拒绝启动。
	host, _, err := net.SplitHostPort(*httpAddr)
	if err != nil || (host != "127.0.0.1" && host != "localhost" && host != "::1") {
		fmt.Fprintln(os.Stderr, "ERROR: http addr must be localhost-only (127.0.0.1 / ::1), got:", *httpAddr)
		os.Exit(1)
	}

	kc := kclient.New(*socket)
	mgr := runmgr.New(runmgr.Config{
		KernelSocket: *socket,
		RuntimeCmd:   splitCmd(*runtimeCmd),
		Watchdog:     *watchdog,
	})
	mgr.SetSessionHooks(
		func(p, s string) (string, error) { return kc.StartSession(context.Background(), p, s) },
		func(sid, reason string) error { return kc.EndSession(context.Background(), sid, reason) },
	)

	hub := ws.New()
	mgr.SetEventSink(hub) // manager 作为事件汇聚点，兜底事件也经 hub 扇出

	// 订阅 Kernel 全量事件流 → 投到 runmgr 事件环 + hub 扇出。
	// 流断时自动重连（指数退避）。
	go func() {
		backoff := time.Second
		for {
			err := kc.Subscribe(context.Background(), "", func(e *pb.Event) {
				mgr.RouteEvent(e) // manager 是事件汇聚点：进环 + 扇出 hub
			})
			if err != nil {
				fmt.Fprintf(os.Stderr, "subscribe stream ended: %v; reconnecting in %v\n", err, backoff)
				time.Sleep(backoff)
				if backoff < 30*time.Second {
					backoff *= 2
				}
				continue
			}
			backoff = time.Second // 流正常结束后重置
			time.Sleep(time.Second)
		}
	}()

	h := api.New(mgr, hub,
		[]string{"./policies", "./examples/policies"},
		[]string{"./examples/sanitization"},
	)
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
	mux.HandleFunc("/api/sanitizations", h.ListSanitizations)
	// WS 事件流。用 websocket.Server（而非 Handler）以跳过 Origin 校验：
	// localhost-only 网关，靠绑定 127.0.0.1 限制访问，无需 Origin 检查。
	// （Handler 默认校验 Origin，会拒绝非浏览器/无 Origin 客户端，返回 403。）
	eventsWS := &websocket.Server{
		Handshake: func(_ *websocket.Config, _ *http.Request) error { return nil },
		Handler: func(ws *websocket.Conn) {
			h.ServeEventsWS(netWSConn{ws})
		},
	}
	mux.Handle("/api/events", eventsWS)

	// 托管前端静态文件（//go:embed 打包进二进制）。
	dist, _ := fs.Sub(web.Dist, "dist")
	fileServer := http.FileServer(http.FS(dist))
	mux.Handle("/", fileServer)

	ln, err := net.Listen("tcp", *httpAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen:", err)
		os.Exit(1)
	}
	fmt.Printf("agentos-gateway on http://%s (kernel socket %s)\n", *httpAddr, *socket)
	if err := http.Serve(ln, mux); err != nil {
		fmt.Fprintln(os.Stderr, "serve:", err)
		os.Exit(1)
	}
}

// splitCmd 把 "python -m agentos_runtime" 拆成 ["python","-m","agentos_runtime"]。
// MVP 用 strings.Fields（含引号场景未处理，YAGNI）。
func splitCmd(s string) []string {
	return strings.Fields(s)
}

// netWSConn 把 *websocket.Conn 适配为 api.WSConn。
type netWSConn struct {
	ws *websocket.Conn
}

func (c netWSConn) Query(key string) string {
	return c.ws.Request().URL.Query().Get(key)
}

func (c netWSConn) SendJSON(v any) error {
	return websocket.JSON.Send(c.ws, v)
}

func (c netWSConn) Close() error {
	return c.ws.Close()
}

// 编译期确保 json 被引用（websocket.JSON 内部用，但显式引用防 goimports 误删）。
var _ = json.Marshal
