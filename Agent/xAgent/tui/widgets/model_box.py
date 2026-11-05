"""侧边栏的模型区：点一下就能换模型。

单独做成 widget 是因为它要可点击。整块 Sidebar 是 VerticalScroll，
把点击区域分开更好处理，也能单独加 hover 高亮。
"""
from rich.text import Text
from textual.message import Message
from textual.widgets import Static


class ModelBox(Static):
    """显示当前模型，点击弹出选择器。"""

    class Clicked(Message):
        """被点了。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = ""

    def set_model(self, model):
        self._model = model or "（未配置）"
        self.refresh()

    def render(self):
        head = Text()
        head.append("模型", style="bold #94a3b8")
        head.append("   点击切换 ▸", style="dim #475569")

        body = Text("  ")
        body.append(self._model, style="#7dd3fc")

        return Text("\n").join([head, body])

    def on_click(self):
        self.post_message(self.Clicked())
