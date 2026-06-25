package scheduler

import (
	"context"
	"sync"
	"testing"
	"time"
)

func TestConcurrencyLimit(t *testing.T) {
	s := New(2) // 最多 2 个并发
	var active, max int
	var mu sync.Mutex

	run := func() {
		ctx := context.Background()
		release, err := s.Acquire(ctx)
		if err != nil {
			t.Fatalf("acquire: %v", err)
		}
		defer release()
		mu.Lock()
		active++
		if active > max {
			max = active
		}
		mu.Unlock()
		time.Sleep(20 * time.Millisecond)
		mu.Lock()
		active--
		mu.Unlock()
	}

	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); run() }()
	}
	wg.Wait()
	if max > 2 {
		t.Errorf("max concurrent = %d, want <= 2", max)
	}
}

func TestAcquireCancelledContext(t *testing.T) {
	s := New(1)
	release, _ := s.Acquire(context.Background())
	defer release()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if _, err := s.Acquire(ctx); err == nil {
		t.Error("expected timeout error when slot unavailable")
	}
}

func TestReleaseAllowsNext(t *testing.T) {
	s := New(1)
	release1, _ := s.Acquire(context.Background())

	// 第二个 acquire 在 goroutine 里等
	got := make(chan struct{})
	go func() {
		release2, _ := s.Acquire(context.Background())
		close(got)
		release2()
	}()

	select {
	case <-got:
		t.Error("second acquire should block until first released")
	case <-time.After(50 * time.Millisecond):
		// 预期阻塞
	}

	release1() // 释放第一个

	select {
	case <-got:
		// 第二个拿到了
	case <-time.After(500 * time.Millisecond):
		t.Error("second acquire should succeed after first released")
	}
}
