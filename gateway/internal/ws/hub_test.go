package ws

import (
	"testing"
	"time"

	pb "agentos/pb"
)

func TestHubFiltersByRunID(t *testing.T) {
	h := New()
	ch := h.Subscribe("r1")
	h.RouteEvent(fakeEvent("runtime.step", "r2")) // 不匹配，应丢弃
	h.RouteEvent(fakeEvent("runtime.step", "r1")) // 匹配

	select {
	case e := <-ch:
		if e.RunId != "r1" {
			t.Errorf("got run %s, want r1", e.RunId)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for matched event")
	}
}

func TestHubSubscribesAllWhenRunIDEmpty(t *testing.T) {
	h := New()
	ch := h.Subscribe("")
	h.RouteEvent(fakeEvent("runtime.step", "anyrun"))
	select {
	case e := <-ch:
		if e.Type != "runtime.step" {
			t.Errorf("got %s", e.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out")
	}
}

func TestHubUnsubscribeStopsDelivery(t *testing.T) {
	h := New()
	ch := h.Subscribe("r1")
	h.Unsubscribe(ch)
	h.RouteEvent(fakeEvent("runtime.step", "r1"))
	// channel 已关闭，range 退出；读取应立即得到零值/关闭
	_, ok := <-ch
	if ok {
		t.Error("channel should be closed after unsubscribe")
	}
}

func fakeEvent(etype, runID string) *pb.Event {
	return &pb.Event{Type: etype, RunId: runID}
}
