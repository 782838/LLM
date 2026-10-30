"""消息卡片：用户消息和助手回答各用一种样式。

参照 opencode 的对话流形态：每条消息独立成块，带角色标识和左边框，
不再是混在一起的一行行文本。

注意：这里用 render() 而不是 update()。
Static.update() 会触发重新布局，而布局测量阶段又会回调 render，
在 __init__ 里调 update 会造成递归，Textual 会报 visual 为 None。
实现 render() 让框架按需取内容就没事了。
"""
from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import Static


ROLE_STYLE = {
    "user": ("你", "bold #7dd3fc", "#3b82f6"),
    "assistant": ("助手", "bold #86efac", "#22c55e"),
    "system": ("系统", "bold #fbbf24", "#f59e0b"),
    "error": ("错误", "bold #fca5a5", "#ef4444"),
}


class MessageCard(Static):
    """一条消息。流式期间追加文本，结束后可切成 Markdown 渲染。"""

    def __init__(self, role="assistant", content="", streaming=False, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self._content = content
        self._streaming = streaming

    # ---- 渲染 ----
    def render(self):
        label, label_style, accent = ROLE_STYLE.get(self.role, ROLE_STYLE["assistant"])

        body = self._content
        if not body and self._streaming:
            body = "…"

        header = Text()
        header.append("▌ ", style=accent)
        header.append(label, style=label_style)
        if self._streaming:
            header.append("  ●", style="blink " + accent)

        # 流式结束后，助手消息按 Markdown 渲染，代码块和列表能正常显示
        if self.role == "assistant" and not self._streaming and body:
            return Group(header, Markdown(body))

        lines = [header]
        for line in (body or "").splitlines() or [""]:
            t = Text("  ")
            t.append(line, style="white" if self.role != "error" else "#fca5a5")
            lines.append(t)
        return Text("\n").join(lines)

    # ---- 内容更新 ----
    def set_content(self, text, streaming=False):
        self._content = text
        self._streaming = streaming
        self.refresh()

    def append_text(self, piece):
        self._content += piece
        self.refresh()

    def finish(self, text=None):
        if text is not None:
            self._content = text
        self._streaming = False
        self.refresh()


class ToolCard(Static):
    """工具调用卡片。执行中显示转圈，完成显示结果摘要。"""

    def __init__(self, name, arguments=None, **kwargs):
        super().__init__(**kwargs)
        self.tool_name = name
        self.arguments = arguments or {}
        self._result = None
        self._error = None

    def _format_args(self):
        if not self.arguments:
            return ""
        parts = []
        for k, v in self.arguments.items():
            s = str(v).replace("\n", "\\n")
            if len(s) > 36:
                s = s[:36] + "…"
            parts.append("%s=%s" % (k, s))
        return ", ".join(parts)

    def render(self):
        line = Text()
        if self._error is not None:
            line.append("  ✗ ", style="bold #ef4444")
            state_style = "#ef4444"
        elif self._result is None:
            line.append("  ⏳ ", style="#fbbf24")
            state_style = "#fbbf24"
        else:
            line.append("  ✓ ", style="bold #22c55e")
            state_style = "#22c55e"

        line.append(self.tool_name, style="bold " + state_style)
        args = self._format_args()
        if args:
            line.append("(" + args + ")", style="dim #94a3b8")

        lines = [line]

        payload = self._error if self._error is not None else self._result
        if payload:
            text = str(payload)
            rows = text.splitlines()
            for i, row in enumerate(rows[:3]):
                t = Text("     ")
                t.append(("└ " if i == 0 else "  ") + row[:110], style="dim #94a3b8")
                lines.append(t)
            if len(rows) > 3:
                more = Text("     ")
                more.append("… 还有 %d 行" % (len(rows) - 3), style="dim #64748b")
                lines.append(more)

        return Text("\n").join(lines)

    def set_result(self, result, error=None):
        self._result = result
        self._error = error
        self.refresh()
