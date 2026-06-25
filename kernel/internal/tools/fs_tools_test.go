package tools

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestFSReadPermissionKey(t *testing.T) {
	r := FSReadTool{}.PermissionKey(map[string]any{"path": "a/b.csv"})
	if r.Type != "path" || r.ID != "a/b.csv" {
		t.Errorf("got %+v", r)
	}
}

func TestFSReadExecute(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "hello.txt")
	_ = os.WriteFile(path, []byte("hi"), 0644)

	res, err := FSReadTool{}.Execute(context.Background(), map[string]any{"path": path})
	if err != nil {
		t.Fatal(err)
	}
	if res.Data["content"] != "hi" {
		t.Errorf("content = %v", res.Data["content"])
	}
}

func TestFSWriteAtomicThenRead(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "sub", "out.txt")
	writeTool := FSWriteTool{}
	readTool := FSReadTool{}
	if _, err := writeTool.Execute(context.Background(), map[string]any{"path": target, "content": "boom"}); err != nil {
		t.Fatal(err)
	}
	res, _ := readTool.Execute(context.Background(), map[string]any{"path": target})
	if res.Data["content"] != "boom" {
		t.Errorf("got %v", res.Data["content"])
	}
	// 原子写不应残留 .tmp 文件
	if _, err := os.Stat(target + ".tmp"); !os.IsNotExist(err) {
		t.Error("residual .tmp file found")
	}
}

func TestFSListExecute(t *testing.T) {
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "a.txt"), []byte("x"), 0644)
	_ = os.WriteFile(filepath.Join(dir, "b.txt"), []byte("x"), 0644)
	res, err := FSListTool{}.Execute(context.Background(), map[string]any{"path": dir})
	if err != nil {
		t.Fatal(err)
	}
	names, _ := res.Data["entries"].([]string)
	if len(names) != 2 {
		t.Errorf("got %d entries", len(names))
	}
}

func TestRegistryDispatch(t *testing.T) {
	r := NewRegistry()
	r.Register(FSReadTool{})
	t_, ok := r.Get("fs_read")
	if !ok {
		t.Fatal("fs_read not registered")
	}
	if t_.Name() != "fs_read" {
		t.Errorf("name = %q", t_.Name())
	}
}

func TestSchemaReturnsValidJSON(t *testing.T) {
	for _, tool := range []Tool{FSReadTool{}, FSWriteTool{}, FSListTool{}} {
		if !json.Valid(tool.Schema()) {
			t.Errorf("%s schema is not valid JSON", tool.Name())
		}
	}
}

func TestRegistryGetUnknownReturnsFalse(t *testing.T) {
	r := NewRegistry()
	if _, ok := r.Get("nonexistent"); ok {
		t.Error("unknown tool should return false")
	}
}
