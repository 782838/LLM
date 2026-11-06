"""xAgent 的终端界面。

参照 opencode 的对话流形态：
    左侧边栏放上下文信息，右侧是消息卡片流，底部是输入区。
业务逻辑一行都没有 —— core/ 完全不知道界面的存在。

几个关键设计：
    - 斜杠命令统一由 tui/commands.py 定义，这里只负责执行
    - 输入 / 自动弹出补全面板
    - MCP 在后台线程异步连接，连完刷新侧边栏，不阻塞界面启动
    - 首次运行没有 config.ini 时自动生成并弹窗提示
"""
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Static

from core import agents_md
from core import bootstrap
from core import models as models_mod
from core import session as session_mod
from core.agent import Agent
from core.config import find_config, load, ConfigError
from core.settings import settings

from . import commands as cmd_mod
from . import events
from .command_palette import CommandPalette
from .compact_view import CompactView
from .exit_dialog import ExitSaveDialog
from .model_picker import ModelPicker
from .session_picker import SessionPicker
from .widgets import Conversation, PromptInput, Sidebar


class FirstRunDialog(ModalScreen):
    """首次运行提示：配置文件刚生成，改完要重启。"""

    BINDINGS = [Binding("escape", "close", "关闭", show=True)]

    CSS = """
    FirstRunDialog {
        align: center middle;
    }

    #firstrun-box {
        width: 76;
        height: 16;
        background: #111827;
        border: thick #fbbf24;
        padding: 1 2;
    }

    #firstrun-title {
        height: 1;
        color: #fde68a;
        text-style: bold;
    }

    #firstrun-body {
        height: 1fr;
        color: #cbd5e1;
    }

    #firstrun-foot {
        height: 3;
        align: right middle;
    }
    """

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def compose(self):
        with Vertical(id="firstrun-box"):
            yield Static("首次运行：已生成配置文件", id="firstrun-title")
            yield Static(
                "配置文件已创建：\n\n%s\n\n"
                "请打开它，把 base_url / model / api_key 改成你自己的配置，"
                "然后**重新启动程序**才能正常对话。\n\n"
                "现在可以先用 /help 看看有哪些命令。" % self.path,
                id="firstrun-body",
            )
            with Horizontal(id="firstrun-foot"):
                yield Button("知道了", id="firstrun-ok", variant="primary")

    def on_button_pressed(self, event):
        if event.button.id == "firstrun-ok":
            self.dismiss(None)

    def action_close(self):
        self.dismiss(None)


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
    background: #111827;
    border-right: solid #1e293b;
    padding: 1 1;
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

#prompt-row {
    height: 4;
}

#stop-btn {
    width: 10;
    height: 3;
    margin: 0 1 0 0;
    display: none;
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
        Binding("ctrl+c", "interrupt_or_quit", "中断/退出", show=True),
        Binding("ctrl+n", "do_new", "新会话", show=True),
        Binding("ctrl+m", "pick_model", "模型", show=True),
        Binding("ctrl+l", "do_clear", "清屏", show=True),
        Binding("f1", "do_tools", "工具", show=True),
        Binding("f2", "do_skills", "技能", show=True),
    ]

    def __init__(self, agent=None, config_path=None, skip_bootstrap=False):
        super().__init__()
        self._agent = agent
        self._config_path = config_path
        self._skip_bootstrap = skip_bootstrap
        self._busy = False
        self._where = ""
        self._mcp_ready = False
        self._bootstrap = None
        # 退出流程防重入：弹窗期间再按 Ctrl+C 不重复弹
        self._exiting = False

    # ---- 组装 ----
    def compose(self):
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical():
                yield Conversation(id="conversation")
                yield CommandPalette(id="palette")
        yield Static("", id="status")
        with Horizontal(id="prompt-row"):
            yield PromptInput(id="prompt")
            yield Button("停止", id="stop-btn", variant="error")
        yield Static(
            " Enter 发送   / 命令   Ctrl+J 换行   Ctrl+M 模型   Ctrl+N 新会话   F1 工具   F2 技能",
            id="prompt-hint",
        )
        yield Footer()

    def on_mount(self):
        # 侧边栏宽度从配置读
        try:
            self.query_one("#sidebar").styles.width = settings.sidebar_width
        except Exception:
            pass

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

    # ---- 退出 ----
    def request_exit(self):
        """所有退出路径的唯一入口：先决定要不要保存，再真的退。

        Ctrl+C 空闲时、/quit、点窗口关闭都走这里，避免有的路存有的路不存。
        """
        if self._exiting:
            return
        agent = self._agent

        # 没东西可存就直接退
        if agent is None or not agent.has_unsaved():
            self.exit()
            return

        # 配置成不询问：按 auto_save_on_exit 静默处理
        if not settings.ask_save_on_exit:
            if settings.auto_save_on_exit:
                agent.save_session()
            self.exit()
            return

        self._exiting = True
        self.push_screen(
            ExitSaveDialog(
                turns=agent.turn_count(),
                preview=session_mod.preview_of(agent.history),
                session_id=agent.session_id,
            ),
            self._after_exit_choice,
        )

    def _after_exit_choice(self, choice):
        """用户选完：save / discard / None（取消）。"""
        self._exiting = False
        if choice is None:
            self.query_one("#prompt", PromptInput).focus()
            return

        if choice == "save":
            sid, detail = self._agent.save_session()
            if sid:
                # 存成功才退；存失败留在界面，别把会话弄丢
                self.exit()
                return
            self.query_one(Conversation).add_error("保存失败，没有退出：%s" % detail)
            self.query_one("#prompt", PromptInput).focus()
            return

        self.exit()

    # ---- 初始化 ----
    def _setup_agent(self):
        conv = self.query_one(Conversation)

        # 首次运行：确保有配置文件
        if not self._skip_bootstrap:
            self._bootstrap = bootstrap.ensure_config()

        if self._agent is None:
            try:
                cfg = load(self._config_path or "config.ini")
                self._agent = Agent(config=cfg, auto_load_mcp=False)
                self._where = find_config(self._config_path or "config.ini") or ""
            except ConfigError as e:
                self._agent = Agent(auto_load_mcp=False)
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

        # 开新会话，顺便注入 AGENTS.md
        injected, note = agent.start_session()

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
        if injected:
            conv.add_system(note)
        elif note and "没有" not in note:
            conv.add_system("AGENTS.md：" + note)

        self._set_status()

        # 异步连 MCP：界面先出来，连接在后台跑
        self._start_mcp()

        # 首次运行弹窗
        if self._bootstrap and self._bootstrap.created:
            self.push_screen(FirstRunDialog(self._bootstrap.path))
        elif self._bootstrap and self._bootstrap.error:
            conv.add_error("生成配置文件失败：%s" % self._bootstrap.error)

    # ---- MCP 异步加载 ----
    def _start_mcp(self):
        """在后台线程连 MCP，连完刷新侧边栏。"""
        sidebar = self.query_one(Sidebar)

        if not settings.mcp_enabled:
            sidebar.mcp_disabled()
            return

        sidebar.mcp_loading()

        agent = self._agent

        def work():
            """后台线程：连接所有 MCP 服务器。"""
            from core.mcp.manager import McpManager

            mgr = McpManager(root=agent.root)
            mgr.connect_all()
            return mgr

        self.run_worker(work, thread=True, exclusive=False, name="mcp-connect")

    def _on_mcp_connected(self, mgr):
        """MCP 连完了，更新侧边栏和工具表。"""
        agent = self._agent
        agent.mcp = mgr
        agent.mcp_notes = list(mgr.notes)

        # 把 MCP 工具注册进现有工具表
        if mgr.tools:
            added = mgr.register_into(agent.tools)
        else:
            added = 0

        # 整理成侧边栏要的数据
        servers = []
        for s in mgr.servers:
            if s.error:
                servers.append((s.name, [], s.error))
            else:
                names = [getattr(t, "name", "?") for t in s.tools]
                servers.append((s.name, names, None))

        sidebar = self.query_one(Sidebar)
        sidebar.mcp_update(servers, mgr.describe())
        self._mcp_ready = True

        conv = self.query_one(Conversation)
        if mgr.tools:
            conv.add_system("MCP 已连接：%s，新增 %d 个工具" % (mgr.describe(), added))
        elif mgr.servers:
            conv.add_system("MCP：%s" % mgr.describe())
            for note in mgr.notes[:3]:
                conv.add_system("  ! " + note)
        else:
            conv.add_system("MCP：没有配置服务器")

        # 工具数变了，刷新状态栏和侧边栏
        # 注意：这里必须带上 turns，否则 MCP 后台连完会把已经聊过的轮数刷回 0
        sidebar.setup(agent.config.model, agent.tool_names(),
                      agent.skills, agent.skill_notes,
                      turns=agent.turn_count())
        self._set_status()

    def _set_status(self, override=None):
        if override:
            self.query_one("#status", Static).update(override)
            return
        try:
            self._update_context_status()
        except Exception:
            pass

    def _update_context_status(self):
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
        if self._mcp_ready and agent.mcp is not None:
            parts.append("MCP %d" % len(agent.mcp.tools))
        if usage.should_warn:
            parts.append("⚠ 需 /compact")

        self.query_one("#status", Static).update("  │  ".join(parts))

    # ---- 用户输入 ----
    def on_prompt_input_submitted(self, event):
        text = event.value
        self.query_one("#prompt", PromptInput).clear_text()
        self.query_one(CommandPalette).hide_panel()

        conv = self.query_one(Conversation)

        # 斜杠命令走单独分支
        if text.startswith("/"):
            self._run_command(text)
            return

        # 正在生成时再发消息 = 插话：先中断当前回答，再处理这条新消息
        if self._busy:
            conv.add_system("已中断上一个回答，正在处理你刚发的消息…")
            self.action_stop()
            # 给被中断的 worker 一点时间收尾，再发新消息
            self.set_timer(0.3, lambda: self._ask(text))
            return

        self._ask(text)

    def _ask(self, text):
        """真正发起一轮提问。"""
        conv = self.query_one(Conversation)

        ok, reason = self._agent.can_accept_input()
        if not ok:
            conv.add_error(reason)
            self._update_context_status()
            return

        conv.add_user(text)
        self._busy = True
        self._show_stop_button(True)
        self._set_status("思考中…（Ctrl+C 或点「停止」可中断）")
        self.run_worker(lambda: self._agent.ask(text), thread=True, exclusive=True)

    def action_stop(self):
        """中断当前生成。按钮和快捷键都走这里。"""
        if not self._busy:
            return
        self._agent.request_stop()
        self.query_one(Conversation).add_system("正在中断…")

    def action_interrupt_or_quit(self):
        """Ctrl+C：正在生成就中断，空闲时才退出（退出前问要不要存）。"""
        if self._busy:
            self.action_stop()
            return
        self.request_exit()

    def on_button_pressed(self, event):
        """停止按钮。"""
        if event.button.id == "stop-btn":
            self.action_stop()
            event.stop()

    def _show_stop_button(self, show):
        try:
            btn = self.query_one("#stop-btn", Button)
            btn.display = show
        except Exception:
            pass

    def on_prompt_input_changed(self, event):
        """输入变化时更新补全面板。"""
        palette = self.query_one(CommandPalette)
        try:
            text = event.text_area.text
        except AttributeError:
            text = (event.value or "")
        palette.update_filter(text)

    def on_command_palette_chosen(self, event):
        """Tab 补全：把命令名填进输入框。"""
        cmd = event.command
        prompt = self.query_one("#prompt", PromptInput)
        prompt.text = cmd.text + " "
        self.query_one(CommandPalette).hide_panel()

    # ---- 命令执行 ----
    def _run_command(self, text):
        cmd = cmd_mod.resolve(text)
        conv = self.query_one(Conversation)

        if cmd is None:
            word = text.strip().split()[0] if text.strip() else text
            conv.add_error("未知命令：%s。输入 /help 看可用命令。" % word)
            return

        handler = getattr(self, cmd.handler, None)
        if handler is None:
            conv.add_error("命令 %s 还没实现" % cmd.text)
            return

        handler()

    # ---- 各命令的具体实现 ----
    def do_new(self):
        """新建会话，先把当前会话保存掉。"""
        conv = self.query_one(Conversation)
        agent = self._agent

        if self._busy:
            conv.add_error("上一轮还没结束，稍等。")
            return

        saved_msg = ""
        if agent.history and settings.auto_save_on_new:
            sid, detail = agent.save_session()
            if sid:
                saved_msg = "已把上一个会话保存为 %s。" % sid
            else:
                saved_msg = "上一个会话保存失败：%s" % detail

        injected, note = agent.start_session()

        conv.remove_children()
        if saved_msg:
            conv.add_system(saved_msg)
        conv.add_system("已开始新会话。")
        if injected:
            conv.add_system(note)

        sidebar = self.query_one(Sidebar)
        sidebar.setup(agent.config.model, agent.tool_names(),
                      agent.skills, agent.skill_notes,
                      turns=agent.turn_count())
        self._update_context_status()
        self.query_one("#prompt", PromptInput).focus()

    def do_save(self):
        """保存当前会话。"""
        conv = self.query_one(Conversation)
        sid, detail = self._agent.save_session()
        if sid:
            conv.add_system(
                "已保存会话 %s（%d 轮）" % (sid, self._agent.turn_count())
            )
            self._update_context_status()
        else:
            conv.add_error("保存失败：%s" % detail)

    def do_resume(self):
        """弹出历史会话列表。"""
        conv = self.query_one(Conversation)
        if self._busy:
            conv.add_error("上一轮还没结束，稍等。")
            return

        sessions = self._agent.list_sessions()
        self.push_screen(SessionPicker(sessions), self._after_resume)

    def _after_resume(self, session_id):
        if not session_id:
            return

        conv = self.query_one(Conversation)
        ok, detail = self._agent.resume_session(session_id)
        if not ok:
            conv.add_error(detail)
            return

        # 把恢复的历史渲染到对话区
        conv.remove_children()
        conv.add_system(detail)
        for msg in self._agent.history:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and content:
                conv.add_user(str(content)[:2000])
            elif role == "assistant" and content:
                conv.add_answer(str(content)[:2000])

        sidebar = self.query_one(Sidebar)
        sidebar.setup(self._agent.config.model, self._agent.tool_names(),
                      self._agent.skills, self._agent.skill_notes,
                      turns=self._agent.turn_count())
        self._update_context_status()
        self.query_one("#prompt", PromptInput).focus()

    def do_compact(self):
        self.action_compact()

    def do_model(self):
        self.action_pick_model()

    def do_tools(self):
        conv = self.query_one(Conversation)
        names = self._agent.tool_names()
        conv.add_system("可用工具（%d 个）：%s" % (len(names), "、".join(names)))

    def do_skills(self):
        conv = self.query_one(Conversation)
        skills = self._agent.skills
        if not skills:
            conv.add_system("没有加载到技能。技能放在 <项目根>/.agents/skills/ 下。")
            return
        lines = ["已加载 %d 个技能：" % len(skills)]
        for s in skills:
            lines.append("  · %s —— %s" % (s.name, s.description))
        conv.add_system("\n".join(lines))

    def do_mcp(self):
        conv = self.query_one(Conversation)
        agent = self._agent
        if not settings.mcp_enabled:
            conv.add_system("MCP 已关闭（config.ini 里 [mcp] enabled = false）")
            return
        if not self._mcp_ready:
            conv.add_system("MCP 还在连接中，稍等…")
            return
        if agent.mcp is None:
            conv.add_system("MCP 没有初始化。")
            return

        lines = ["MCP：%s" % agent.mcp.describe()]
        for line in agent.mcp.status_lines():
            lines.append("  " + line)
        for note in agent.mcp_notes[:5]:
            lines.append("  ! " + note)
        conv.add_system("\n".join(lines))

    def do_context(self):
        conv = self.query_one(Conversation)
        usage = self._agent.context_usage()
        lines = [
            "上下文用量：%s" % usage.summary(),
            "  已用：%d tokens" % usage.used,
            "  窗口：%d tokens%s" % (usage.window, "（默认值）" if usage.is_default else ""),
            "  剩余：%d tokens" % usage.remaining,
            "  数据来源：%s" % ("模型返回的真实用量" if usage.exact else "本地估算"),
            "  警告阈值：达到 %.0f%% 时提示压缩" % (settings.warn_ratio * 100),
            "",
            "历史消息：%d 条" % len(self._agent.history),
            "当前会话：%s" % (self._agent.session_id or "（还没保存）"),
        ]
        conv.add_system("\n".join(lines))

    def do_clear(self):
        """清屏 + 清历史。

        只清屏不清 history 会骗人：看着干净了，token 照烧、模型照样记得
        之前聊的。所以这里一并 reset，并在提示里说清楚。
        没聊过的会话不弹确认，聊过才问一句，避免误删。
        """
        conv = self.query_one(Conversation)

        if self._busy:
            conv.add_error("上一轮还没结束，稍等再清空。")
            return

        if not self._agent.history:
            conv.remove_children()
            return

        from .confirm import ConfirmDialog

        def apply(ok):
            if not ok:
                return
            self._agent.reset()
            self._agent.start_session()
            conv.remove_children()
            conv.add_system("已清空对话历史和屏幕。当前会话从头开始。")
            self._sync_turns()
            self._update_context_status()
            self.query_one("#prompt", PromptInput).focus()

        self.push_screen(
            ConfirmDialog(
                "清空对话",
                "这会清掉屏幕和全部对话历史（%d 轮）。\n"
                "没保存的内容会丢失。要清空吗？" % self._agent.turn_count(),
                ok_text="清空",
            ),
            apply,
        )

    def do_help(self):
        self.query_one(Conversation).add_system(cmd_mod.help_text())

    def do_quit(self):
        self.request_exit()

    def action_quit(self):
        """Textual 自带的退出动作也拦下来，走统一的保存询问。"""
        self.request_exit()

    # ---- 压缩 ----
    def action_compact(self):
        conv = self.query_one(Conversation)

        if self._busy:
            conv.add_error("上一轮还没结束，稍等再压缩。")
            return

        usage = self._agent.context_usage()
        if usage.used < 100:
            conv.add_system("当前会话内容很少，不需要压缩。")
            return

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
        from textual.worker import WorkerState

        # MCP 连接完成
        if event.worker.name == "mcp-connect":
            if event.state == WorkerState.SUCCESS:
                self._on_mcp_connected(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self.query_one(Sidebar).mcp_update(
                    [], "连接出错：%s" % event.worker.error
                )
                self.query_one(Conversation).add_error(
                    "MCP 连接出错：%s" % event.worker.error
                )
            return

        # 压缩完成
        if event.worker.name == "compact":
            if event.state != WorkerState.SUCCESS:
                self._busy = False
                self._show_stop_button(False)
                self._set_status()
                self.query_one(Conversation).add_error(
                    "压缩过程出错：%s" % event.worker.error
                )
                return

            ok, payload = event.worker.result
            self._busy = False
            self._show_stop_button(False)
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

        # 模型列表
        self._handle_model_worker(event)

    def _finish_turn(self):
        self._busy = False
        self._show_stop_button(False)
        self._sync_turns()
        self._update_context_status()
        self.query_one("#prompt", PromptInput).focus()

    def _sync_turns(self):
        """侧边栏轮数按 agent.history 实算，不靠进程内计数器。

        计数器只在「这一轮没调工具」时才加，调了工具、被中断、报错的轮次
        都会漏掉，所以必须从历史里数。
        """
        try:
            self.query_one(Sidebar).set_turns(self._agent.turn_count())
        except Exception:
            pass

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

    # ---- 模型切换 ----
    def on_model_box_clicked(self, _event):
        self.action_pick_model()

    def action_pick_model(self):
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
            % (model_id, old,
               "，配置已写回 " + detail if ok else "，但写回配置失败：" + detail)
        )
        sb = self.query_one(Sidebar)
        sb.setup(model_id, self._agent.tool_names(), self._agent.skills,
                 self._agent.skill_notes, turns=0)
        self._set_status()


def run(config_path=None):
    """启动终端界面。"""
    XAgentApp(config_path=config_path).run()
