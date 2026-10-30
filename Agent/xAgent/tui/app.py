"""xAgent 的终端界面。

参照 opencode 的对话流形态重写过：
    左侧边栏放上下文信息，右侧是消息卡片流，底部是输入区。
业务逻辑一行都没有 —— core/ 完全不知道界面的存在。
"""
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from core.agent import Agent
from core.config import find_config, load, ConfigError

from . import events
from .widgets import Conversation, PromptInput, Sidebar

CSS = """
Screen {
    background: #0f172a;
    color: #e2e8f0;
}

Header {
    background: #1e293b;
    color: #e2e8f0;
}

Footer {
    background: #1e293b;
    color: #94a3b8;
}

#body {
    height: 1fr;
}

/* ---------- 侧边栏 ---------- */
#sidebar {
    width: 28;
    background: #111827;
    border-right: solid #1e293b;
    padding: 1 1;
}

#sidebar-body {
    width: 100%;
}

/* ---------- 对话区 ---------- */
#conversation {
    height: 1fr;
    padding: 1 2;
    scrollbar-size: 1 1;
}

.msg {
    margin: 0 0 1 0;
    padding: 0 1;
}

.msg-user {
    background: #172554;
    border-left: thick #3b82f6;
}

.msg-assistant {
    background: #14532d 12%;
    border-left: thick #22c55e;
}

.msg-tool {
    background: #1e293b;
    border-left: thick #a855f7;
}

.msg-error {
    background: #450a0a;
    border-left: thick #ef4444;
}

.msg-system {
    background: #1e293b;
    border-left: thick #f59e0b;
}

/* ---------- 输入区 ---------- */
#status {
    height: 1;
    background: #1e293b;
    color: #94a3b8;
    padding: 0 2;
}

#prompt {
    height: 4;
    background: #111827;
    border: round #334155;
    padding: 0 1;
    margin: 0 1;
}

#prompt:focus {
    border: round #3b82f6;
}

#prompt-hint {
    height: 1;
    color: #64748b;
    padding: 0 2;
}
"""


class XAgentApp(App):
    """把 core.agent.Agent 包成一个终端应用。"""

    TITLE = "xAgent"
    SUB_TITLE = "core + tui"
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", show=True),
        Binding("ctrl+n", "new_session", "新会话", show=True),
        Binding("ctrl+l", "clear", "清屏", show=True),
        Binding("f1", "show_tools", "工具", show=True),
        Binding("f2", "show_skills", "技能", show=True),
    ]

    def __init__(self, agent=None, config_path=None):
        super().__init__()
        self._agent = agent
        self._config_path = config_path
        self._busy = False
        self._where = ""

    # ---- 组装 ----
    def compose(self):
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            yield Conversation(id="conversation")
        yield Static("", id="status")
        yield PromptInput(id="prompt")
        yield Static(
            " Enter 发送   Ctrl+J 换行   Ctrl+N 新会话   Ctrl+L 清屏   F1 工具   F2 技能",
            id="prompt-hint",
        )
        yield Footer()

    def on_mount(self):
        self._setup_agent()
        self.query_one("#prompt", PromptInput).focus()

    # ---- 初始化 ----
    def _setup_agent(self):
        conv = self.query_one(Conversation)

        if self._agent is None:
            try:
                cfg = load(self._config_path or "config.ini")
                self._agent = Agent(config=cfg)
                self._where = find_config(self._config_path or "config.ini") or ""
            except ConfigError as e:
                self._agent = Agent()
                conv.add_error(str(e))
                self._set_status("配置缺失")
                return
        else:
            self._where = "(由调用方注入)"

        agent = self._agent
        agent.on_assistant_start = lambda: self.post_message(events.AssistantStart())
        agent.on_assistant_delta = lambda t: self.post_message(events.AssistantDelta(t))
        agent.on_assistant_end = lambda t, c: self.post_message(events.AssistantEnd(t, c))
        agent.on_tool_start = lambda n, a: self.post_message(events.ToolStarted(n, a))
        agent.on_tool_end = lambda n, r, e: self.post_message(events.ToolFinished(n, r, e))
        agent.on_error = lambda m: self.post_message(events.AgentFailed(m))

        sidebar = self.query_one(Sidebar)
        sidebar.setup(
            agent.config.model,
            agent.tool_names(),
            agent.skills,
            agent.skill_notes,
        )

        conv.add_system(
            "输入问题后回车发送。技能从 .agents/skills/ 加载，正文按需通过 loadSkill 拉取。"
        )
        self._set_status()

    def _set_status(self, override=None):
        if override:
            text = override
        else:
            agent = self._agent
            model = agent.config.model or "（未配置模型）"
            text = "%s  │  %d 工具  │  %d 技能  │  %s" % (
                model,
                len(agent.tools),
                len(agent.skills),
                self._where or "-",
            )
        self.query_one("#status", Static).update(text)

    # ---- 用户输入 ----
    def on_prompt_input_submitted(self, event):
        text = event.value
        self.query_one("#prompt", PromptInput).clear_text()

        conv = self.query_one(Conversation)
        if self._busy:
            conv.add_error("上一轮还没结束，稍等。")
            return

        conv.add_user(text)
        self._busy = True
        self._set_status("思考中…")
        self.run_worker(lambda: self._agent.ask(text), thread=True, exclusive=True)

    def _finish_turn(self):
        self._busy = False
        self.query_one(Sidebar).bump_turn()
        self._set_status()
        self.query_one("#prompt", PromptInput).focus()

    # ---- Agent 事件 ----
    def on_assistant_start(self, _event):
        self.query_one(Conversation).start_assistant()

    def on_assistant_delta(self, event):
        self.query_one(Conversation).push_delta(event.text)

    def on_assistant_end(self, event):
        conv = self.query_one(Conversation)
        conv.end_assistant(event.text)
        if not event.calls:
            self._finish_turn()

    def on_tool_started(self, event):
        self.query_one(Conversation).add_tool(event.name, event.arguments)

    def on_tool_finished(self, event):
        self.query_one(Conversation).set_tool_result(
            event.name, event.result, event.error
        )

    def on_agent_failed(self, event):
        self.query_one(Conversation).add_error(event.message)
        self._finish_turn()

    # ---- 快捷键 ----
    def action_new_session(self):
        self._agent.reset()
        conv = self.query_one(Conversation)
        conv.remove_children()
        conv.add_system("已开新会话，历史已清空。")
        self.query_one(Sidebar).setup(
            self._agent.config.model,
            self._agent.tool_names(),
            self._agent.skills,
            self._agent.skill_notes,
        )

    def action_clear(self):
        conv = self.query_one(Conversation)
        conv.remove_children()

    def action_show_tools(self):
        conv = self.query_one(Conversation)
        names = self._agent.tool_names()
        conv.add_system("可用工具（%d 个）：%s" % (len(names), "、".join(names)))

    def action_show_skills(self):
        conv = self.query_one(Conversation)
        skills = self._agent.skills
        if not skills:
            conv.add_system("没有加载到技能。技能放在 <项目根>/.agents/skills/ 下。")
            return
        lines = ["已加载 %d 个技能：" % len(skills)]
        for s in skills:
            lines.append("  · %s —— %s" % (s.name, s.description))
        conv.add_system("\n".join(lines))


def run(config_path=None):
    """启动终端界面。"""
    XAgentApp(config_path=config_path).run()
