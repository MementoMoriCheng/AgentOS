import threading


class Scheduler:
    """用信号量限制并发 agent 数。FIFO 公平(threading.Semaphore)。
    Week 1 同步实现;Week 2 改 asyncio.Semaphore + 多副本。"""

    def __init__(self, max_concurrent: int):
        self._sem = threading.Semaphore(max_concurrent)

    def acquire(self):
        """占一个并发槽。返回 release 函数释放槽。"""
        self._sem.acquire()
        return self._sem.release
