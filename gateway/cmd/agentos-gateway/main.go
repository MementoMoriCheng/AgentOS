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
	runtimeCmd := fs.String("runtime", "python -m agentos_runtime", "runtime command")
	fs.Parse(os.Args[1:])

	fmt.Printf("agentos-gateway: kernel socket %s, http %s, runtime %q\n", *socket, *httpAddr, *runtimeCmd)
	fmt.Println("(REST/WS 接入见 Task 8)")
	select {} // Task 8 替换为真实 http.Serve
}
