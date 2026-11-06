"""xAgent 的终端界面。

参照 opencode 的对话流形态重写过：
    左侧边栏放上下文信息，右侧是消息卡片流，底部是输入区。
业务逻辑一行都没有 —— core/ 完全不知道界面的存在。
"""
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from core import models as models_mod
from core.agent import Agent
from core.config import find_config, load, ConfigError

from . import events
from .compact_view import CompactView
from .model_picker import ModelPicker
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
        Binding("ctrl+m", "pick_model", "模型", show=True),
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

    def on_unmount(self):
        """退出时关掉 MCP 会话，别留后台线程。"""
        agent = self._agent
        if agent is not None:
            try:
                agent.close()
            except Exception:
                pass

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
        # MCP 连接情况单独提示，方便确认 .mcp.json 有没有被扫到
        if self._agent.mcp is not None:
            conv.add_system("MCP：%s" % self._agent.mcp_summary())
            for line in self._agent.mcp.status_lines():
                conv.add_system("  " + line)
            for note in self._agent.mcp_notes:
                conv.add_system("  ! " + note)
        self._set_status()

    def _set_status(self, override=None):
        """刷新状态栏。

        override 用于临时提示（「思考中…」这类），
        正常状态下会带上上下文用量。
        """
        if override:
            self.query_one("#status", Static).update(override)
            return

        try:
            self._update_context_status()
        except Exception:
            pass

    # ---- 用户输入 ----
    def on_prompt_input_submitted(self, event):
        text = event.value
        self.query_one("#prompt", PromptInput).clear_text()

        conv = self.query_one(Conversation)

        # 斜杠命令走单独的分支，不当成提示词发给模型
        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._busy:
            conv.add_error("上一轮还没结束，稍等。")
            return

        # 上下文超阈值时拦住输入，只有 /compact 能过
        ok, reason = self._agent.can_accept_input()
        if not ok:
            conv.add_error(reason)
            self._update_context_status()
            return

        conv.add_user(text)
        self._busy = True
        self._set_status("思考中…")
        self.run_worker(lambda: self._agent.ask(text), thread=True, exclusive=True)

    def _handle_command(self, text):
        """处理斜杠命令。"""
        conv = self.query_one(Conversation)
        cmd = text.strip().lower()

        if cmd in ("/compact", "/c"):
            self.action_compact()
        elif cmd in ("/help", "/?"):
            conv.add_system(
                "可用命令：\n"
                "  /compact  压缩上下文（超阈值时必需）\n"
                "  /help     显示这条帮助\n"
                "快捷键：Ctrl+M 换模型，Ctrl+N 新会话，F1 工具，F2 技能"
            )
        else:
            conv.add_error(
                "未知命令：%s。可用命令：/compact、/help" % text.strip()
            )

    # ---- 上下文压缩 ----
    def action_compact(self):
        """执行 /compact。"""
        conv = self.query_one(Conversation)

        if self._busy:
            conv.add_error("上一轮还没结束，稍等再压缩。")
            return

        usage = self._agent.context_usage()
        if usage.used < 100:
            conv.add_system("当前会话内容很少，不需要压缩。")
            return

        # 对话太短时压缩会失败（摘要不可能比原文更短），提前拦住
        from core import context as ctx_mod

        hist_tokens = ctx_mod.history_tokens(self._agent.history)
        if hist_tokens < 800:
            conv.add_system(
                "当前历史只有约 %d tokens，压缩不会有收益"
                "（摘要很难比原文更短）。等对话长一些再压缩。" % hist_tokens
            )
            return

        conv.add_system("开始压缩上下文，正在归档原始记录…")
        self._busy = True
        self._set_status("压缩中…")

        def progress(*args):
            """从工作线程里更新界面要 post 消息。"""
            self.call_from_thread(self._on_compact_progress, *args)

        def work():
            return self._agent.compact(on_event=progress)

        self.run_worker(work, thread=True, exclusive=True, name="compact")

    def _on_compact_progress(self, stage, *args):
        conv = self.query_one(Conversation)
        if stage == "archiving":
            conv.add_system("正在归档原始上下文…")
        elif stage == "summarizing":
            conv.add_system("正在调用模型生成摘要…")
        elif stage == "failed":
            conv.add_error("压缩失败：%s" % (args[0] if args else ""))

    def on_worker_state_changed(self, event):
        """压缩 worker 结束后处理结果。"""
        from textual.worker import WorkerState

        if event.worker.name == "compact":
            if event.state != WorkerState.SUCCESS:
                self._busy = False
                self._set_status()
                self.query_one(Conversation).add_error(
                    "压缩过程出错：%s" % event.worker.error
                )
                return

            ok, payload = event.worker.result
            self._busy = False
            self._update_context_status()

            if not ok:
                self.query_one(Conversation).add_error(str(payload))
                return

            self.push_screen(CompactView(payload))
            self.query_one(Conversation).add_system(
                "上下文已压缩，归档编号 %s。可以继续对话了。"
                % payload.get("archive_id", "?")
            )
            self.query_one("#prompt", PromptInput).focus()
            return

        # 模型列表是另一个 worker，交给原来的处理函数
        self._handle_model_worker(event)

    def _finish_turn(self):
        self._busy = False
        self.query_one(Sidebar).bump_turn()
        self._update_context_status()
        self.query_one("#prompt", PromptInput).focus()

    def _update_context_status(self):
        """刷新状态栏，显示上下文用量。"""
        try:
            usage = self._agent.context_usage()
        except Exception:
            return

        agent = self._agent
        parts = [
            agent.config.model or "（未配置模型）",
            "%d 工具" % len(agent.tools),
            "%d 技能" % len(agent.skills),
            "上下文 %s" % usage.summary(),
        ]

        if usage.should_warn:
            parts.append("⚠ 需 /compact")

        self.query_one("#status", Static).update("  │  ".join(parts))

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

    # ---- 切换模型 ----
    def on_model_box_clicked(self, _event):
        """点侧边栏的模型区，弹出选择器。"""
        self.action_pick_model()

    def action_pick_model(self):
        """Ctrl+M：弹出模型选择器。"""
        conv = self.query_one(Conversation)
        if self._busy:
            conv.add_system("上一轮还没结束，稍等一下再换模型。")
            return

        cfg = self._agent.config
        conv.add_system("正在获取可用模型…")

        def fetch():
            return models_mod.list_models(cfg)

        self.run_worker(fetch, thread=True, exclusive=False,
                        name="list-models", group="models")

    def _handle_model_worker(self, event):
        """模型列表 worker 结束后弹选择器。"""
        from textual.worker import WorkerState

        if event.worker.name != "list-models":
            return
        if event.state != WorkerState.SUCCESS:
            return

        models, note = event.worker.result
        current = self._agent.config.model

        def apply(chosen):
            if chosen:
                self._switch_model(chosen)

        self.push_screen(ModelPicker(models, current, note), apply)

    def _switch_model(self, model_id):
        """切到指定模型：改内存里的配置，写回 config.ini，重置会话。"""
        conv = self.query_one(Conversation)
        old = self._agent.config.model
        if model_id == old:
            conv.add_system("模型没变，还是 %s" % model_id)
            return

        ok, detail = models_mod.save_model(model_id)
        self._agent.config.model = model_id
        self._agent.reset()
        conv.add_system(
            "已切换到 %s（原 %s）%s\n会话历史已清空，避免旧上下文干扰新模型。"
            % (model_id, old, "，配置已写回 " + detail if ok else "，但写回配置失败：" + detail)
        )
        sb = self.query_one(Sidebar)
        sb.setup(model_id, self._agent.tool_names(), self._agent.skills,
                 self._agent.skill_notes)
        self._set_status()


def run(config_path=None):
    """启动终端界面。"""
    XAgentApp(config_path=config_path).run()
