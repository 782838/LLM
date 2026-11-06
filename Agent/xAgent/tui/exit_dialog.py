"""退出前的「要不要保存这次会话」弹窗。

三条路都会走到这里：Ctrl+C 空闲时、/quit、点窗口关闭。
不给用户选就直接丢会话，等于白聊一场。
"""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ExitSaveDialog(ModalScreen):
    """退出前问一句：保存、丢弃、还是取消退出。

    返回值：
        "save"    保存后再退
        "discard" 不保存直接退
        None      取消退出，回界面
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=True),
        Binding("s", "save", "保存", show=True),
        Binding("d", "discard", "丢弃", show=True),
    ]

    CSS = """
    ExitSaveDialog {
        align: center middle;
    }

    #exit-box {
        width: 72;
        height: 14;
        background: #111827;
        border: thick #f59e0b;
        padding: 1 2;
    }

    #exit-title {
        height: 1;
        color: #fde68a;
        text-style: bold;
    }

    #exit-body {
        height: 1fr;
        color: #cbd5e1;
    }

    #exit-foot {
        height: 3;
        align: center middle;
    }

    #exit-foot Button {
        margin: 0 1;
    }
    """

    def __init__(self, turns, preview, session_id=None, **kwargs):
        super().__init__(**kwargs)
        self.turns = turns
        self.preview = preview or ""
        self.session_id = session_id

    def compose(self):
        target = self.session_id or "（还没保存过，将新建）"
        with Vertical(id="exit-box"):
            yield Static("退出前保存这次会话？", id="exit-title")
            yield Static(
                "本次会话：%d 轮对话\n摘要：%s\n存档名：%s\n\n"
                "保存后可以用 /resume 找回来。"
                % (self.turns, self.preview or "（无）", target),
                id="exit-body",
            )
            with Horizontal(id="exit-foot"):
                yield Button("保存并退出 (S)", id="exit-save", variant="success")
                yield Button("不保存 (D)", id="exit-discard", variant="error")
                yield Button("取消 (Esc)", id="exit-cancel", variant="default")

    def on_button_pressed(self, event):
        if event.button.id == "exit-save":
            self.dismiss("save")
        elif event.button.id == "exit-discard":
            self.dismiss("discard")
        elif event.button.id == "exit-cancel":
            self.dismiss(None)

    def action_save(self):
        self.dismiss("save")

    def action_discard(self):
        self.dismiss("discard")

    def action_cancel(self):
        self.dismiss(None)
