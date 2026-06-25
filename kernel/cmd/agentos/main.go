package main

import (
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"

	"google.golang.org/grpc"

	"agentos/kernel/internal/audit"
	pb "agentos/pb"
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
	// Kernel 认证第一层：socket 文件权限 0600，只有 owner 能连。
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
		// 当成 session id 处理
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
