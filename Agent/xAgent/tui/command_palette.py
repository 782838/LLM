"""斜杠命令补全面板。

贴在输入框上方的一个小浮层，输入 / 时自动出现，
继续打字就过滤，上下键选择，回车确认，Esc 关掉。
"""
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from . import commands as cmd_mod


class CommandPalette(Static):
    """命令补全列表。"""

    BINDINGS = [
        Binding("up", "move_up", "上", show=False),
        Binding("down", "move_down", "下", show=False),
        Binding("tab", "complete", "补全", show=False),
    ]

    DEFAULT_CSS = """
    CommandPalette {
        height: auto;
        max-height: 12;
        background: #0f172a;
        border: round #3b82f6;
        padding: 0 1;
        display: none;
    }

    CommandPalette.visible {
        display: block;
    }
    """

    class Chosen(Message):
        """用户选中了一条命令。"""

        def __init__(self, command):
            self.command = command
            super().__init__()

    class Cancelled(Message):
        """用户取消了。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._items = []
        self._index = 0
        self._typed = ""

    # ---- 显示控制 ----
    def update_filter(self, typed):
        """按输入内容过滤。typed 是输入框里的完整内容。"""
        self._typed = typed or ""

        if not self._typed.startswith("/"):
            self.hide_panel()
            return

        self._items = cmd_mod.suggest(self._typed)
        if not self._items:
            self.hide_panel()
            return

        self._index = 0
        self.add_class("visible")
        self.refresh()

    def hide_panel(self):
        self._items = []
        self._index = 0
        self.remove_class("visible")
        self.refresh()

    @property
    def visible(self):
        return bool(self._items)

    # ---- 渲染 ----
    def render(self):
        if not self._items:
            return Text("")

        lines = []
        for i, c in enumerate(self._items):
            line = Text()
            if i == self._index:
                line.append("▶ ", style="bold #3b82f6")
                style = "bold #e0e7ff"
            else:
                line.append("  ")
                style = "#94a3b8"

            line.append(c.text.ljust(12), style=style)
            line.append(c.description, style="#64748b" if i != self._index else "#cbd5e1")
            lines.append(line)

        return Text("\n").join(lines)

    # ---- 选择 ----
    def action_move_up(self):
        if not self._items:
            return
        self._index = (self._index - 1) % len(self._items)
        self.refresh()

    def action_move_down(self):
        if not self._items:
            return
        self._index = (self._index + 1) % len(self._items)
        self.refresh()

    def action_complete(self):
        """Tab：只把名字补进输入框，不执行。"""
        if self._items:
            self.post_message(self.Chosen(self._items[self._index]))

    def current(self):
        """当前高亮的命令。"""
        if self._items and 0 <= self._index < len(self._items):
            return self._items[self._index]
        return None