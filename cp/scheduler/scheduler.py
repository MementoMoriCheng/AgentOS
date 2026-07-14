import asyncio


class Scheduler:
    """用信号量限制并发 agent 数。asyncio.Semaphore(单事件循环内 FIFO 公平)。"""

    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max_concurrent)

    async def acquire(self):
        """占一个并发槽。返回 release 函数释放槽。"""
        await self._sem.acquire()
        return self._sem.release
