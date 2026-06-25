package sandbox

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveInsideRoot(t *testing.T) {
	dir := t.TempDir()
	abs, err := Resolve(filepath.Join(dir, "a.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if abs != filepath.Join(dir, "a.txt") {
		t.Errorf("got %q", abs)
	}
}

func TestResolveRejectsTraversal(t *testing.T) {
	// Resolve 只防"未规范化的相对路径里残留的 .. 段"。
	// 注意：防"绝对路径越界"不是 Resolve 的职责，而是 Gate（基于 pattern 边界）。
	// filepath.Clean("a/../../../etc") 会留下 ".."（因为 .. 是根，无法继续消化）。
	_, err := Resolve("a/../../../etc/passwd")
	if err == nil {
		t.Error("expected traversal (relative .. escaping root) rejected")
	}
}

func TestResolveRejectsSymlinkEscape(t *testing.T) {
	dir := t.TempDir()
	target := t.TempDir()
	if err := os.WriteFile(filepath.Join(target, "secret"), []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(dir, "escape")); err != nil {
		t.Skip("symlink not supported here:", err)
	}
	_, err := Resolve(filepath.Join(dir, "escape", "secret"))
	if err == nil {
		t.Error("expected symlink escape rejected")
	}
}

func TestResolveCreatesParentForNonexistent(t *testing.T) {
	// 目标文件还不存在（如 fs_write 场景）：应能解析父目录并返回可写路径
	dir := t.TempDir()
	target := filepath.Join(dir, "newdir", "out.txt")
	abs, err := Resolve(target)
	if err != nil {
		t.Fatalf("resolve nonexistent target: %v", err)
	}
	if filepath.Base(abs) != "out.txt" {
		t.Errorf("got base %q", filepath.Base(abs))
	}
}
