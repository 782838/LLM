"""对话流容器：纵向堆叠消息卡片和工具卡片，自动滚动到底部。"""
from textual.containers import VerticalScroll

from .message import MessageCard, ToolCard


class Conversation(VerticalScroll):
    """一条消息一个卡片，从上往下排。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_assistant = None
        self._assistant_buffer = ""
        self._pending_tools = {}

    # ---- 用户 ----
    def add_user(self, text):
        self._current_assistant = None
        self._assistant_buffer = ""
        self.mount(MessageCard("user", text, classes="msg msg-user"))
        self._scroll_end()

    # ---- 助手 ----
    def start_assistant(self):
        self._assistant_buffer = ""
        self._current_assistant = None

    def push_delta(self, text):
        if self._current_assistant is None:
            card = MessageCard("assistant", "", classes="msg msg-assistant")
            self.mount(card)
            self._current_assistant = card
        self._assistant_buffer += text
        self._current_assistant.append_text(text)
        self._scroll_end()

    def end_assistant(self, text=None):
        if self._current_assistant is not None:
            final = text if text else self._assistant_buffer
            self._current_assistant.finish(final)
        self._current_assistant = None
        self._assistant_buffer = ""
        self._scroll_end()

    def add_answer(self, text):
        """没有流式时直接补一条完整回答。"""
        if text:
            self.mount(MessageCard("assistant", text, classes="msg msg-assistant"))
            self._scroll_end()

    # ---- 工具 ----
    def add_tool(self, name, arguments):
        # 工具调用前先把当前这一段助手的流式内容收尾
        if self._current_assistant is not None:
            self._current_assistant.finish(self._assistant_buffer)
            self._current_assistant = None
            self._assistant_buffer = ""

        card = ToolCard(name, arguments, classes="msg msg-tool")
        self._pending_tools[name] = card
        self.mount(card)
        self._scroll_end()
        return card

    def set_tool_result(self, name, result, error):
        card = self._pending_tools.pop(name, None)
        if card is not None:
            card.set_result(result, error)
        self._scroll_end()

    # ---- 其他 ----
    def add_error(self, message):
        self.mount(MessageCard("error", message, classes="msg msg-error"))
        self._scroll_end()

    def add_system(self, text):
        self.mount(MessageCard("system", text, classes="msg msg-system"))
        self._scroll_end()

    def _scroll_end(self):
        self.call_after_refresh(self.scroll_end, animate=False)
