"""历史会话选择器：/resume 弹这个。

列表显示会话时间、摘要、轮数，上下键选，回车恢复，Esc 取消。
"""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static


class SessionPicker(ModalScreen):
    """选一个历史会话恢复。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=True),
    ]

    CSS = """
    SessionPicker {
        align: center middle;
    }

    #session-box {
        width: 88;
        height: 26;
        background: #111827;
        border: thick #22c55e;
        padding: 1 2;
    }

    #session-title {
        height: 1;
        color: #bbf7d0;
        text-style: bold;
    }

    #session-hint {
        height: 1;
        color: #64748b;
    }

    #session-list {
        height: 1fr;
        background: #0f172a;
        border: round #1e293b;
        margin: 1 0;
    }

    #session-status {
        height: 1;
        color: #64748b;
    }

    ListItem {
        padding: 0 1;
    }
    """

    def __init__(self, sessions, **kwargs):
        super().__init__(**kwargs)
        self._sessions = list(sessions)

    def compose(self):
        with Vertical(id="session-box"):
            yield Static("历史会话", id="session-title")
            yield Static("↑↓ 选择　回车恢复　Esc 取消", id="session-hint")
            yield ListView(id="session-list")
            yield Static("", id="session-status")

    def on_mount(self):
        lv = self.query_one("#session-list", ListView)
        if not self._sessions:
            lv.append(ListItem(Label("（还没有保存过会话）")))
            self.query_one("#session-status", Static).update("用 /save 或 /new 可以保存会话")
            return

        for s in self._sessions:
            mark = ""
            if s.model:
                mark = "  [%s]" % s.model
            lv.append(ListItem(Label("%s%s" % (s.preview, mark))))
            # 副标题用 status 行展示更详细的
        self.query_one("#session-status", Static).update(
            "共 %d 个会话　最新的在最上面" % len(self._sessions)
        )

    def on_list_view_selected(self, event):
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._sessions):
            return
        self.dismiss(self._sessions[idx].id)

    def action_cancel(self):
        self.dismiss(None)
