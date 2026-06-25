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

// 接口实现静态断言
var _ Tool = FSReadTool{}
var _ Tool = FSWriteTool{}
var _ Tool = FSListTool{}
