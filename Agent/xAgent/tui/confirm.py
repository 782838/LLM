"""通用确认弹窗。

只用在会丢东西的操作上（比如清空对话历史）。
"""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen):
    """问一句「要不要这么做」。回调拿到 True / False。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=True),
    ]

    CSS = """
    ConfirmDialog {
        align: center middle;
    }

    #confirm-box {
        width: 68;
        height: 13;
        background: #111827;
        border: thick #ef4444;
        padding: 1 2;
    }

    #confirm-title {
        height: 1;
        color: #fecaca;
        text-style: bold;
    }

    #confirm-body {
        height: 1fr;
        color: #cbd5e1;
    }

    #confirm-foot {
        height: 3;
        align: center middle;
    }

    #confirm-foot Button {
        margin: 0 1;
    }
    """

    def __init__(self, title, body, ok_text="确定", cancel_text="取消", **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.body = body
        self.ok_text = ok_text
        self.cancel_text = cancel_text

    def compose(self):
        with Vertical(id="confirm-box"):
            yield Static(self.title, id="confirm-title")
            yield Static(self.body, id="confirm-body")
            with Horizontal(id="confirm-foot"):
                yield Button(self.ok_text, id="confirm-ok", variant="error")
                yield Button(self.cancel_text, id="confirm-cancel", variant="default")

    def on_button_pressed(self, event):
        if event.button.id == "confirm-ok":
            self.dismiss(True)
        elif event.button.id == "confirm-cancel":
            self.dismiss(False)

    def action_cancel(self):
        self.dismiss(False)
