"""MCP 会话管理：连接 Server、列工具、调工具。

会话要**常驻**，不能每次调用都重连。
但 SDK 的 stdio_client / streamable_http_client 都是 async context manager，
用 `async with` 就会在退出时断开。所以这里手工管理：

    ctx = stdio_client(params)
    read, write = await ctx.__aenter__()     手动进入
    session = ClientSession(read, write)
    await session.__aenter__()
    ...                                       一直保持
    await session.__aexit__(...)             关闭时才退出
    await ctx.__aexit__(...)

关键前提：所有操作必须在**同一个事件循环**里。
AsyncRunner 提供了这个循环，所以持锁、进出、调用都通过它调度。
"""
import asyncio

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

try:
    # SDK 2.x 叫 streamable_http_client
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # 兼容旧版命名
    from mcp.client.streamable_http import streamablehttp_client as streamable_http_client

CONNECT_TIMEOUT = 30
LIST_TIMEOUT = 30
CALL_TIMEOUT = 120


class McpSessionError(Exception):
    """会话建立或调用失败。"""


class McpSession:
    """一个到 MCP Server 的常驻会话。"""

    def __init__(self, server, runner):
        self.server = server
        self.runner = runner
        self._session = None
        self._transport_ctx = None

    # ---- 建立连接 ----
    async def _aopen(self):
        """在事件循环里建立连接。"""
        if self.server.is_http:
            self._transport_ctx = streamable_http_client(self.server.url)
        else:
            params = StdioServerParameters(
                command=self.server.command,
                args=self.server.args,
                env=self.server.env or None,
                cwd=self.server.cwd,
            )
            self._transport_ctx = stdio_client(params)

        streams = await self._transport_ctx.__aenter__()

        # 两种 transport 的返回值不同：
        #   stdio            → (read, write)
        #   streamable_http  → TransportStreams(read, write, ...) 或三/四元组
        if isinstance(streams, tuple):
            read, write = streams[0], streams[1]
        else:
            read, write = streams.read_stream, streams.write_stream

        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await asyncio.wait_for(self._session.initialize(), CONNECT_TIMEOUT)
        return self

    def open(self):
        """同步入口：连接并初始化。"""
        self.runner.run(self._aopen(), timeout=CONNECT_TIMEOUT + 10)
        return self

    # ---- 工具 ----
    async def _alist(self):
        result = await asyncio.wait_for(self._session.list_tools(), LIST_TIMEOUT)
        return list(getattr(result, "tools", []) or [])

    def list_tools(self):
        """同步入口：列出工具对象。"""
        return self.runner.run(self._alist(), timeout=LIST_TIMEOUT + 10)

    async def _acall(self, tool_name, arguments):
        return await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments or {}),
            CALL_TIMEOUT,
        )

    def call_tool(self, tool_name, arguments=None):
        """同步入口：调用工具，返回原始 CallToolResult。"""
        return self.runner.run(
            self._acall(tool_name, arguments), timeout=CALL_TIMEOUT + 10
        )

    # ---- 关闭 ----
    async def _aclose(self):
        errs = []
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                errs.append(e)
            self._session = None
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception as e:
                errs.append(e)
            self._transport_ctx = None
        return errs

    def close(self, timeout=15):
        """同步入口：关闭会话。出错不抛，返回错误描述列表。"""
        if self._session is None and self._transport_ctx is None:
            return []
        try:
            errs = self.runner.run(self._aclose(), timeout=timeout)
        except Exception as e:
            return ["关闭会话出错：%s: %s" % (type(e).__name__, e)]
        return ["%s: %s" % (type(e).__name__, e) for e in (errs or [])]

    @property
    def connected(self):
        return self._session is not None
