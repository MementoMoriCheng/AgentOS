from agentos_runtime.rate_limit import AdaptiveRateLimiter


def test_initial_rpm():
    r = AdaptiveRateLimiter(initial_rpm=60)
    assert r.current_rpm() == 60


def test_on429_halves_rpm():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 30
    r.on_429()
    assert r.current_rpm() == 15


def test_on429_does_not_go_below_min():
    r = AdaptiveRateLimiter(initial_rpm=8, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 5  # 4 被钳到 5


def test_on_success_restores_rpm():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5)
    r.on_429()
    assert r.current_rpm() == 30
    r.on_success()
    assert r.current_rpm() == 60  # 恢复


def test_should_wait_after_429():
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5, base_backoff_sec=2.0)
    r.on_429()
    wait = r.should_wait()
    assert wait > 0


def test_should_wait_zero_when_no_backoff():
    r = AdaptiveRateLimiter(initial_rpm=60)
    assert r.should_wait() == 0.0


def test_consecutive_429_increases_backoff():
    # 连续 429 应指数增长退避
    r = AdaptiveRateLimiter(initial_rpm=60, min_rpm=5, base_backoff_sec=1.0)
    r.on_429()
    w1 = r.should_wait()
    r.on_429()
    w2 = r.should_wait()
    assert w2 > w1  # 第二次退避更长
