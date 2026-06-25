package server

import (
	"context"
	"testing"
	"time"

	"google.golang.org/grpc/metadata"

	pb "agentos/pb"
)

// fakeSubscribeStream 实现 pb.Kernel_SubscribeEventsServer（= grpc.ServerStreamingServer[Event]）。
type fakeSubscribeStream struct {
	ctx  context.Context
	recv chan *pb.Event
}

func newFakeSubscribeStream(ctx context.Context) *fakeSubscribeStream {
	return &fakeSubscribeStream{ctx: ctx, recv: make(chan *pb.Event, 8)}
}

func (f *fakeSubscribeStream) Send(e *pb.Event) error {
	f.recv <- e
	return nil
}
func (f *fakeSubscribeStream) Context() context.Context      { return f.ctx }
func (f *fakeSubscribeStream) RecvMsg(any) error             { return nil }
func (f *fakeSubscribeStream) SetHeader(metadata.MD) error   { return nil }
func (f *fakeSubscribeStream) SendHeader(metadata.MD) error  { return nil }
func (f *fakeSubscribeStream) SetTrailer(metadata.MD)        {}
func (f *fakeSubscribeStream) SendMsg(any) error             { return nil }

// TestSubscribeAndEmit 验证 Runtime 经 EmitRuntimeEvent 灌入的事件能被 SubscribeEvents 收到。
func TestSubscribeAndEmit(t *testing.T) {
	s := New("./_test_audit_events")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := newFakeSubscribeStream(ctx)
	// 在 goroutine 里跑 SubscribeEvents（它会阻塞直到 ctx 取消）。
	go func() { _ = s.SubscribeEvents(&pb.SubscribeEventsRequest{}, stream) }()

	// 给订阅一点注册时间。
	time.Sleep(50 * time.Millisecond)

	// Runtime 灌一个事件。
	_, err := s.EmitRuntimeEvent(context.Background(), &pb.Event{
		Type:        "runtime.step",
		SessionId:   "s1",
		RunId:       "r1",
		PayloadJson: `{"step_index":0}`,
	})
	if err != nil {
		t.Fatalf("EmitRuntimeEvent: %v", err)
	}

	select {
	case got := <-stream.recv:
		if got.Type != "runtime.step" || got.RunId != "r1" {
			t.Errorf("unexpected event: type=%s run=%s", got.Type, got.RunId)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for emitted event")
	}
}

// TestSubscribeFiltersBySession 验证 session_id 过滤生效。
func TestSubscribeFiltersBySession(t *testing.T) {
	s := New("./_test_audit_events")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := newFakeSubscribeStream(ctx)
	go func() {
		_ = s.SubscribeEvents(&pb.SubscribeEventsRequest{SessionId: "wanted"}, stream)
	}()
	time.Sleep(50 * time.Millisecond)

	// 灌一个不匹配 session 的事件，不应被收到。
	s.EmitRuntimeEvent(context.Background(), &pb.Event{Type: "runtime.step", SessionId: "other"})
	// 灌一个匹配的事件，应被收到。
	s.EmitRuntimeEvent(context.Background(), &pb.Event{Type: "runtime.step", SessionId: "wanted"})

	select {
	case got := <-stream.recv:
		if got.SessionId != "wanted" {
			t.Errorf("expected filtered event for 'wanted', got %s", got.SessionId)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for filtered event")
	}
}

// TestEndSessionPublishesEnded 验证 EndSession 发布 session.ended 事件。
func TestEndSessionPublishesEnded(t *testing.T) {
	s := New("./_test_audit_events")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := newFakeSubscribeStream(ctx)
	go func() { _ = s.SubscribeEvents(&pb.SubscribeEventsRequest{}, stream) }()
	time.Sleep(50 * time.Millisecond)

	_, err := s.EndSession(context.Background(), &pb.EndSessionRequest{SessionId: "sx", Reason: "completed"})
	if err != nil {
		t.Fatalf("EndSession: %v", err)
	}

	select {
	case got := <-stream.recv:
		if got.Type != "session.ended" {
			t.Errorf("expected session.ended, got %s", got.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for session.ended")
	}
}
