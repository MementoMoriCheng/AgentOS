import threading
import time

from cp.scheduler.scheduler import Scheduler


def test_acquire_release_allows_reuse():
    s = Scheduler(2)
    r1 = s.acquire()
    r2 = s.acquire()
    r1()
    r2()
    r3 = s.acquire()  # 应立即拿到
    r3()


def test_concurrency_limit_enforced():
    s = Scheduler(1)
    held = threading.Event()
    release = threading.Event()
    results = []

    def holder():
        r = s.acquire()
        held.set()
        release.wait()
        r()

    t = threading.Thread(target=holder)
    t.start()
    held.wait()
    # 此时槽被占,acquire 应阻塞
    got = threading.Event()

    def waiter():
        r = s.acquire()
        got.set()
        r()

    tw = threading.Thread(target=waiter)
    tw.start()
    time.sleep(0.05)
    assert not got.is_set()  # 仍阻塞
    release.set()
    t.join()
    tw.join()
    assert got.is_set()
