"""后台事件循环：把 async 函数桥接成同步调用。

为什么需要它
------------
现有 xAgent 整条链路是同步的 —— Registry.execute() 是普通函数，
Agent 用 urllib 发请求，没有任何 await。
而 MCP SDK 全是 async：连接、list_tools、call_tool 都要 await。

方案
----
起一个 daemon 线程，在里面常驻一个事件循环。
主线程要调 async 函数时，用 run_coroutine_threadsafe 把协程提交进去，
再阻塞等结果。这样会话可以常驻，不用每次调用都重连。
"""
import asyncio
import threading


class RunnerClosed(Exception):
    """事件循环已经关闭。"""


class AsyncRunner:
    """一个后台线程 + 一个常驻事件循环。"""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._closed = False

    # ---- 生命周期 ----
    def start(self, timeout=10):
        """启动后台线程和事件循环。重复调用是安全的。"""
        if self._thread is not None and self._thread.is_alive():
            return self

        self._closed = False
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._serve, name="mcp-async-runner", daemon=True
        )
        self._thread.start()

        if not self._ready.wait(timeout):
            raise RuntimeError("后台事件循环启动超时（%s 秒）。" % timeout)
        return self

    def _serve(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                # 收尾：取消所有残留任务，避免退出时报警告
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            finally:
                loop.close()

    def close(self, timeout=10):
        """停掉事件循环和线程。"""
        self._closed = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None
        self._loop = None

    @property
    def running(self):
        return (
            not self._closed
            and self._loop is not None
            and self._loop.is_running()
        )

    # ---- 桥接 ----
    def run(self, coro, timeout=60):
        """同步执行一个协程，返回结果。"""
        if self._closed:
            raise RunnerClosed("事件循环已关闭，无法执行。")
        if not self.running:
            self.start()

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise TimeoutError("异步操作超时（%s 秒）。" % timeout)
        except Exception:
            # 协程内部抛的异常原样往上抛，让调用方决定怎么处理
            raise

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False
