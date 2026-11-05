"""MCP 管理器：一次性做完连接、列工具、包装注册。

对外只暴露 McpManager，Agent 只需要：

    manager = McpManager(root=skills_root)
    manager.connect_all()          # 失败的 Server 记进 notes，不中断
    manager.register_into(registry)
    ...
    manager.close()

故障隔离
--------
每个 Server 独立 try，一个连不上不影响其他，也不影响本地 19 个工具。
"""
import os

from . import adapter, config as mcp_config
from .client import McpSession
from .runner import AsyncRunner


class McpManager:
    """管所有 MCP Server 的连接和工具。"""

    def __init__(self, root=None, runner=None):
        self.root = root or os.getcwd()
        self._runner = runner
        self._owns_runner = runner is None
        self.servers = []
        self.sessions = {}
        self.tools = []          # 包装好的 Tool 列表
        self.notes = []          # 给人看的提示（连不上、跳过原因等）
        self.config_error = None

    # ---- 建立 ----
    def connect_all(self):
        """读配置并逐个连接。任何单个失败都不抛异常。"""
        try:
            self.servers, cfg_notes = mcp_config.load(self.root)
        except mcp_config.McpConfigError as e:
            self.config_error = str(e)
            self.notes.append(str(e))
            return self

        self.notes.extend(cfg_notes)

        if not self.servers:
            return self

        if self._runner is None:
            self._runner = AsyncRunner()
        self._runner.start()

        for server in self.servers:
            self._connect_one(server)

        return self

    def _connect_one(self, server):
        """连一个 Server 并注册它的工具。"""
        session = McpSession(server, self._runner)
        try:
            session.open()
        except Exception as e:
            server.error = "%s: %s" % (type(e).__name__, e)
            self.notes.append(
                "MCP Server「%s」连接失败：%s" % (server.name, server.error)
            )
            try:
                session.close(timeout=5)
            except Exception:
                pass
            return

        try:
            tool_defs = session.list_tools()
        except Exception as e:
            server.error = "%s: %s" % (type(e).__name__, e)
            self.notes.append(
                "MCP Server「%s」列出工具失败：%s" % (server.name, server.error)
            )
            session.close(timeout=5)
            return

        if not tool_defs:
            self.notes.append("MCP Server「%s」没有提供任何工具。" % server.name)
            session.close(timeout=5)
            return

        self.sessions[server.name] = session
        server.tools = tool_defs

        for tool_def in tool_defs:
            try:
                tool = adapter.make_tool(server.name, tool_def, session)
            except Exception as e:
                self.notes.append(
                    "MCP 工具「%s/%s」包装失败：%s" % (
                        server.name, getattr(tool_def, "name", "?"), e)
                )
                continue
            self.tools.append(tool)

    # ---- 注册 ----
    def register_into(self, registry):
        """把包装好的工具塞进已有的 Registry。

        撞名时不覆盖已有工具，记一笔提示。
        """
        added = 0
        for tool in self.tools:
            if tool.name in registry:
                self.notes.append(
                    "MCP 工具「%s」与已有工具重名，已跳过。" % tool.name
                )
                continue
            registry.register(tool)
            added += 1
        return added

    # ---- 状态 ----
    @property
    def connected_servers(self):
        return list(self.sessions)

    def describe(self):
        """给界面显示的一句话摘要。"""
        if not self.servers:
            return "无 MCP Server"
        ok = len(self.sessions)
        total = len(self.servers)
        return "%d/%d 个 MCP Server，%d 个工具" % (ok, total, len(self.tools))

    def status_lines(self):
        """逐条状态，给界面或自检用。"""
        lines = []
        for s in self.servers:
            if s.error:
                lines.append("%s：失败（%s）" % (s.name, s.error))
            elif s.name in self.sessions:
                lines.append("%s：已连接，%d 个工具" % (s.name, len(s.tools)))
            else:
                lines.append("%s：未连接" % s.name)
        return lines

    # ---- 清理 ----
    def close(self):
        """关闭所有会话和事件循环。"""
        errors = []
        for name, session in list(self.sessions.items()):
            try:
                errs = session.close()
                if errs:
                    errors.append("%s: %s" % (name, "; ".join(errs)))
            except Exception as e:
                errors.append("%s: %s: %s" % (name, type(e).__name__, e))
        self.sessions.clear()

        if self._owns_runner and self._runner is not None:
            try:
                self._runner.close()
            except Exception as e:
                errors.append("关闭事件循环失败：%s" % e)
            self._runner = None

        return errors

    def __enter__(self):
        return self.connect_all()

    def __exit__(self, *exc):
        self.close()
        return False
