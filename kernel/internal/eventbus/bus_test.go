package eventbus

import (
	"sync"
	"testing"
)

func TestPublishDeliversToSubscriber(t *testing.T) {
	b := NewInProcess()
	var got []Event
	b.Subscribe(func(e Event) { got = append(got, e) })
	b.Publish(Event{Type: "tool.called", SessionID: "s1"})
	if len(got) != 1 || got[0].Type != "tool.called" {
		t.Fatalf("got %v", got)
	}
}

func TestMultipleSubscribers(t *testing.T) {
	b := NewInProcess()
	var n int
	var mu sync.Mutex
	b.Subscribe(func(e Event) { mu.Lock(); n++; mu.Unlock() })
	b.Subscribe(func(e Event) { mu.Lock(); n++; mu.Unlock() })
	b.Publish(Event{Type: "x"})
	if n != 2 {
		t.Errorf("both subscribers should fire, got %d", n)
	}
}

func TestSubscriberPanicDoesNotBreakMain(t *testing.T) {
	b := NewInProcess()
	var reached bool
	b.Subscribe(func(e Event) { panic("boom") })
	b.Subscribe(func(e Event) { reached = true })
	b.Publish(Event{Type: "x"})
	if !reached {
		t.Error("second subscriber should still run after first panicked")
	}
}

func TestEventHasTimestamp(t *testing.T) {
	b := NewInProcess()
	var ts int64
	b.Subscribe(func(e Event) { ts = e.Timestamp })
	b.Publish(Event{Type: "x"})
	if ts == 0 {
		t.Error("timestamp should be set")
	}
}

func TestSubscribeAfterPublish(t *testing.T) {
	// 后订阅的不会收到之前的事件（fire-and-forget）
	b := NewInProcess()
	b.Publish(Event{Type: "early"})
	var got Event
	b.Subscribe(func(e Event) { got = e })
	b.Publish(Event{Type: "late"})
	if got.Type != "late" {
		t.Errorf("should only get late event, got %v", got.Type)
	}
}
