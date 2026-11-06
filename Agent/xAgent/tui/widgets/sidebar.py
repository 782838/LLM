"""左侧边栏：模型（可点击）、工具、技能、MCP、会话信息。"""
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from .model_box import ModelBox


class McpPanel(Static):
    """MCP 服务器与其工具的展示区。

    异步加载时先显示「连接中…」，连完刷新。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = "idle"       # idle / loading / ready / disabled
        self.servers = []         # [(名字, [工具名...], 错误信息或 None)]
        self.note = ""

    def set_loading(self):
        self.state = "loading"
        self.note = "正在连接 MCP 服务器…"
        self.refresh()

    def set_disabled(self):
        self.state = "disabled"
        self.note = "MCP 已关闭（config.ini 里 [mcp] enabled = false）"
        self.refresh()

    def set_servers(self, servers, note=""):
        """servers 是 [(名字, 工具名列表, 错误或 None)]。"""
        self.state = "ready"
        self.servers = list(servers)
        self.note = note
        self.refresh()

    def _render_loading(self):
        lines = [Text("MCP", style="bold #94a3b8")]
        t = Text("  ")
        t.append("◐ " + (self.note or "连接中…"), style="#fbbf24")
        lines.append(t)
        return lines

    def _render_ready(self):
        ok = [s for s in self.servers if not s[2]]
        bad = [s for s in self.servers if s[2]]

        head = Text("MCP ", style="bold #94a3b8")
        head.append("%d/%d" % (len(ok), len(self.servers)), style="#94a3b8")
        lines = [head]

        if not self.servers:
            lines.append(Text("  （没有配置 MCP 服务器）", style="dim #64748b"))
            return lines

        for name, tools, err in self.servers:
            line = Text("  ")
            if err:
                line.append("✗ ", style="bold #ef4444")
                line.append(name, style="#fca5a5")
                lines.append(line)
                # 错误信息截断显示
                e = Text("     ")
                e.append(str(err)[:40], style="dim #7f1d1d")
                lines.append(e)
            else:
                line.append("✓ ", style="bold #22c55e")
                line.append(name, style="#a7f3d0")
                line.append(" (%d)" % len(tools), style="dim #64748b")
                lines.append(line)
                for tool in tools[:4]:
                    t = Text("     ")
                    t.append("· " + str(tool), style="#94a3b8")
                    lines.append(t)
                if len(tools) > 4:
                    more = Text("     ")
                    more.append("… 还有 %d 个" % (len(tools) - 4), style="dim #64748b")
                    lines.append(more)

        return lines

    def render(self):
        if self.state == "loading":
            return Text("\n").join(self._render_loading())
        if self.state == "disabled":
            lines = [Text("MCP", style="bold #94a3b8")]
            t = Text("  ")
            t.append(self.note, style="dim #64748b")
            lines.append(t)
            return Text("\n").join(lines)
        if self.state == "idle":
            lines = [Text("MCP", style="bold #94a3b8")]
            lines.append(Text("  （未初始化）", style="dim #64748b"))
            return Text("\n").join(lines)
        return Text("\n").join(self._render_ready())


class InfoPanel(Static):
    """模型以下的那些信息。数据由 Sidebar 推过来。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tools = []
        self.skills = []
        self.skill_notes = []
        self.turns = 0

    def _section(self, title, items, style="white", limit=None):
        lines = [Text(title, style="bold #94a3b8")]
        shown = items if limit is None else items[:limit]
        for item in shown:
            t = Text("  ")
            t.append("· ", style="#475569")
            t.append(str(item), style=style)
            lines.append(t)
        if limit is not None and len(items) > limit:
            more = Text("  ")
            more.append("… %d 个" % (len(items) - limit), style="dim #64748b")
            lines.append(more)
        return lines

    def render(self):
        blocks = [Text("")]

        blocks.extend(self._section(
            "工具 %d" % len(self.tools), self.tools, style="#a5b4fc", limit=5))
        blocks.append(Text(""))

        names = [s.name for s in self.skills]
        blocks.extend(self._section(
            "技能 %d" % len(names), names, style="#86efac", limit=4))
        for note in self.skill_notes[:2]:
            t = Text("  ")
            t.append("! " + str(note)[:22], style="dim #fbbf24")
            blocks.append(t)
        blocks.append(Text(""))

        blocks.append(Text("会话", style="bold #94a3b8"))
        turn_line = Text("  ")
        turn_line.append("%d 轮对话" % self.turns, style="#cbd5e1")
        blocks.append(turn_line)

        return Text("\n").join(blocks)

    def update_data(self, tools, skills, skill_notes, turns):
        self.tools = list(tools)
        self.skills = list(skills)
        self.skill_notes = list(skill_notes or [])
        self.turns = turns
        self.refresh()


class Sidebar(VerticalScroll):
    """上下文信息面板。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = ""
        self._tools = []
        self._skills = []
        self._skill_notes = []
        self._turns = 0

    def compose(self):
        yield ModelBox(id="model-box")
        yield InfoPanel(id="info-panel")
        yield McpPanel(id="mcp-panel")

    def setup(self, model, tools, skills, skill_notes=None):
        self._model = model or "（未配置）"
        self._tools = list(tools)
        self._skills = list(skills)
        self._skill_notes = list(skill_notes or [])
        self._turns = 0
        self._push()

    def bump_turn(self):
        self._turns += 1
        self._push()

    def _push(self):
        self.query_one("#model-box", ModelBox).set_model(self._model)
        self.query_one("#info-panel", InfoPanel).update_data(
            self._tools, self._skills, self._skill_notes, self._turns
        )

    # ---- MCP 区域 ----
    def mcp_loading(self):
        self.query_one("#mcp-panel", McpPanel).set_loading()

    def mcp_disabled(self):
        self.query_one("#mcp-panel", McpPanel).set_disabled()

    def mcp_update(self, servers, note=""):
        self.query_one("#mcp-panel", McpPanel).set_servers(servers, note)
