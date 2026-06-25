package ws

import (
	"sync"

	pb "agentos/pb"
)

// subscription 是一个 WS 订阅。
type subscription struct {
	runID string
	ch    chan *pb.Event
}

// Hub 把事件扇出给所有订阅者。补播历史由调用方在订阅前从 runmgr 取并先行发送，
// 故 Hub 自身不存事件（单一数据源在 runmgr 事件环）。
type Hub struct {
	mu   sync.Mutex
	subs map[*subscription]struct{}
}

func New() *Hub {
	return &Hub{subs: map[*subscription]struct{}{}}
}

// RouteEvent 把事件扇出给匹配的订阅者。
func (h *Hub) RouteEvent(e *pb.Event) {
	h.mu.Lock()
	subs := make([]*subscription, 0, len(h.subs))
	for s := range h.subs {
		subs = append(subs, s)
	}
	h.mu.Unlock()
	for _, s := range subs {
		// 订阅指定 run 时只收匹配的；runID 为空 = 收全部
		if s.runID != "" && e.RunId != "" && s.runID != e.RunId {
			continue
		}
		select {
		case s.ch <- e:
		default: // 慢消费者丢弃（MVP 简化）
		}
	}
}

// Subscribe 注册一个订阅，返回事件 channel。
// runID 为空表示订阅全部事件。
func (h *Hub) Subscribe(runID string) <-chan *pb.Event {
	sub := &subscription{runID: runID, ch: make(chan *pb.Event, 64)}
	h.mu.Lock()
	h.subs[sub] = struct{}{}
	h.mu.Unlock()
	return sub.ch
}

// Unsubscribe 移除订阅并关闭 channel。
func (h *Hub) Unsubscribe(ch <-chan *pb.Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for s := range h.subs {
		if s.ch == ch {
			close(s.ch)
			delete(h.subs, s)
			return
		}
	}
}
