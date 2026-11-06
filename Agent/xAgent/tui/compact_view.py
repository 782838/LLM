"""上下文压缩对比面板：左原文，右摘要，两栏都能滚。

压缩成功后弹出来，让用户直观看到压掉了什么、留下了什么。
"""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class CompactView(ModalScreen):
    """压缩前后对比。"""

    BINDINGS = [
        Binding("escape", "close", "关闭", show=True),
    ]

    CSS = """
    CompactView {
        align: center middle;
    }

    #compact-box {
        width: 96%;
        height: 90%;
        background: #0f172a;
        border: thick #a855f7;
        padding: 1 2;
    }

    #compact-title {
        height: 1;
        color: #e9d5ff;
        text-style: bold;
    }

    #compact-meta {
        height: 1;
        color: #94a3b8;
    }

    #compact-columns {
        height: 1fr;
    }

    .compact-col {
        width: 1fr;
        height: 100%;
        border: round #334155;
        padding: 0 1;
    }

    .compact-col-title {
        height: 1;
        color: #94a3b8;
        text-style: bold;
    }

    .compact-body {
        height: 1fr;
        background: #0b1220;
        padding: 0 1;
    }

    #compact-foot {
        height: 3;
        align: right middle;
    }
    """

    def __init__(self, result, **kwargs):
        super().__init__(**kwargs)
        self.result = result or {}

    def compose(self):
        r = self.result
        archive = r.get("archive_id", "?")
        before_k = r.get("before_tokens", 0) / 1024.0
        after_k = r.get("after_tokens", 0) / 1024.0

        with Vertical(id="compact-box"):
            yield Static("上下文压缩完成", id="compact-title")
            yield Static(
                "归档编号 %s　压缩前约 %.1fk tokens → 压缩后约 %.1fk tokens"
                % (archive, before_k, after_k),
                id="compact-meta",
            )
            with Horizontal(id="compact-columns"):
                with Vertical(classes="compact-col"):
                    yield Static("压缩前（原始上下文）", classes="compact-col-title")
                    yield Static(
                        Text(r.get("before", "（空）")),
                        classes="compact-body",
                    )
                with Vertical(classes="compact-col"):
                    yield Static("压缩后（摘要）", classes="compact-col-title")
                    yield Static(
                        Text(r.get("after", "（空）")),
                        classes="compact-body",
                    )
            with Horizontal(id="compact-foot"):
                yield Button("关闭", id="compact-close", variant="primary")

    def on_button_pressed(self, event):
        if event.button.id == "compact-close":
            self.dismiss(None)

    def action_close(self):
        self.dismiss(None)
