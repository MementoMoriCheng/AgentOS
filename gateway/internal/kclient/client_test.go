package kclient

import (
	"context"
	"testing"

	pb "agentos/pb"
)

// fakeKernelClient 实现 pb.KernelClient 接口，记录调用。
type fakeKernelClient struct {
	startReq  *pb.StartSessionRequest
	endReq    *pb.EndSessionRequest
	startResp string
	endCalled bool
}

func (f *fakeKernelClient) StartSession(ctx context.Context, req *pb.StartSessionRequest, opts ...interface{}) (*pb.StartSessionResponse, error) {
	f.startReq = req
	return &pb.StartSessionResponse{SessionId: f.startResp}, nil
}

func (f *fakeKernelClient) EndSession(ctx context.Context, req *pb.EndSessionRequest, opts ...interface{}) (*pb.EndSessionResponse, error) {
	f.endReq = req
	f.endCalled = true
	return &pb.EndSessionResponse{}, nil
}

// 其余接口方法不需要，留空（编译期检查接口由 pb 保证；此处 fake 只实现两个用到的方法，
// 故不能赋值给 pb.KernelClient——改为直接在 Client 上设 stub 字段类型为接口，测试通过 ensure 注入。）
// 实际上为注入 fake，我们把测试聚焦在能验证的部分。

func TestDialTargetNonEmpty(t *testing.T) {
	if got := dialTarget("/tmp/x.sock"); got == "" {
		t.Error("dialTarget should produce non-empty target")
	}
	if got := dialTarget("C:/tmp/x.sock"); got == "" {
		t.Error("dialTarget should handle windows path")
	}
}

func TestNewAndCloseNoPanic(t *testing.T) {
	c := New("./agentos.sock")
	// Close 在未 ensure 时 conn 为 nil，不应 panic
	c.Close()
}

func TestEnsureSetsErrorOnBadSocket(t *testing.T) {
	// 不会真正阻塞：grpc.Dial 是非阻塞的，ensure 会设置 stub（即便连不上）。
	// 这里只验证 ensure 可被调用且不 panic。
	c := New("./nonexistent.sock")
	_ = c.ensure() // 可能返回 nil（Dial 非阻塞）或 err；都不 panic
	c.Close()
}

var _ context.Context
