"""模型选择器：一个浮层，列出可用模型，选中后回调。

用 Textual 的 ModalScreen 做成浮层，覆盖在对话区上面。
支持输入关键词过滤、上下键选择、回车确认。
"""
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from core.models import filter_models


class ModelPicker(ModalScreen):
    """选模型的浮层。选中后 dismiss 出模型 id，取消 dismiss 出 None。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=True),
    ]

    CSS = """
    ModelPicker {
        align: center middle;
    }

    #picker-box {
        width: 70;
        height: 24;
        background: #111827;
        border: thick #3b82f6;
        padding: 1 2;
    }

    #picker-title {
        height: 1;
        color: #94a3b8;
        text-style: bold;
    }

    #picker-hint {
        height: 1;
        color: #64748b;
    }

    #picker-filter {
        height: 3;
        background: #0f172a;
        border: round #334155;
        margin: 1 0;
    }

    #picker-filter:focus {
        border: round #3b82f6;
    }

    #picker-list {
        height: 1fr;
        background: #0f172a;
        border: round #1e293b;
    }

    ListItem {
        padding: 0 1;
    }

    ListItem.--highlight {
        background: #1e3a8a;
    }

    #picker-status {
        height: 1;
        color: #64748b;
    }
    """

    def __init__(self, models, current="", note=None, **kwargs):
        super().__init__(**kwargs)
        self._all = list(models)
        self._shown = list(models)
        self._current = current
        self._note = note

    def compose(self):
        with Vertical(id="picker-box"):
            yield Static("选择模型", id="picker-title")
            yield Static(
                "输入关键词过滤，↑↓ 选择，回车确认，Esc 取消", id="picker-hint"
            )
            yield Input(placeholder="过滤…", id="picker-filter")
            yield ListView(id="picker-list")
            yield Static("", id="picker-status")

    def on_mount(self):
        self._fill(self._all)
        self.query_one("#picker-filter", Input).focus()
        total = len(self._all)
        status = "共 %d 个模型" % total
        if self._note:
            status += "（%s，用的是内置清单）" % self._note
        if self._current:
            status += "　当前：%s" % self._current
        self.query_one("#picker-status", Static).update(status)

    def _fill(self, models):
        """重建列表。"""
        from textual.widgets import ListView as LV

        lv = self.query_one("#picker-list", LV)
        lv.clear()
        self._shown = list(models)
        if not models:
            lv.append(ListItem(Label("（没有匹配的模型）")))
            return
        for m in models:
            mark = "  ● " if m.id == self._current else "    "
            lv.append(ListItem(Label(mark + m.id)))

    def on_input_changed(self, event):
        filtered = filter_models(self._all, event.value)
        self._fill(filtered)
        self.query_one("#picker-status", Static).update(
            "匹配 %d / %d 个模型" % (len(filtered), len(self._all))
        )

    def on_input_submitted(self, event):
        """在过滤框里按回车，选中列表第一个。"""
        if self._shown:
            self.dismiss(self._shown[0].id)

    def on_list_view_selected(self, event):
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._shown):
            return
        self.dismiss(self._shown[idx].id)

    def action_cancel(self):
        self.dismiss(None)
