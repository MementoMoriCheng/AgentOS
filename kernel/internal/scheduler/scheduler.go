package scheduler

import "context"

// Scheduler 用信号量限制并发 agent 数。FIFO 公平（Go channel 本质 FIFO）。
// MVP 实现：单一并发上限。未来加优先级调度、多租户配额是扩展。
type Scheduler struct {
	sem chan struct{}
}

func New(maxConcurrent int) *Scheduler {
	return &Scheduler{sem: make(chan struct{}, maxConcurrent)}
}

// Acquire 占一个并发槽。返回 release 函数释放槽。
// ctx 取消时返回 ctx.Err()。
func (s *Scheduler) Acquire(ctx context.Context) (release func(), err error) {
	select {
	case s.sem <- struct{}{}:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return func() { <-s.sem }, nil
}
