"""TUI 层测试：命令执行、补全面板、MCP 侧边栏异步刷新。"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.agent import Agent
from tui.app import XAgentApp
from tui.command_palette import CommandPalette
from tui.widgets import Conversation, Sidebar
from tui.widgets.sidebar import McpPanel

passed = 0
failed = []


def check(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("OK   %s" % label)
    else:
        failed.append(label)
        print("FAIL %s  %s" % (label, detail))


ROOT = tempfile.mkdtemp(prefix="uitest_")
os.makedirs(os.path.join(ROOT, ".agents", "skills"), exist_ok=True)


class FakeAgent(Agent):
    def __init__(self):
        super().__init__(auto_load_skills=False, auto_load_mcp=False,
                         skills_root=ROOT)

    def ask(self, text):
        return "假回答"


class _FakeMcp:
    """假的 McpManager：只为测 _on_mcp_connected 的侧边栏刷新。"""

    def __init__(self):
        self.tools = []
        self.servers = []
        self.notes = []

    def describe(self):
        return "0/0 个 MCP Server"

    def register_into(self, registry):
        return 0

    def status_lines(self):
        return []


def conv_text(conv):
    from rich.console import Console
    import io

    out = []
    for w in conv.children:
        buf = io.StringIO()
        try:
            Console(file=buf, width=100).print(w.render())
        except Exception:
            continue
        out.append(buf.getvalue())
    return "\n".join(out)


async def main():
    app = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)

    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()

        conv = app.query_one(Conversation)
        palette = app.query_one(CommandPalette)
        sidebar = app.query_one(Sidebar)

        check("应用启动", app.is_running)
        check("补全面板存在", palette is not None)
        check("侧边栏有 MCP 区域", sidebar.query_one(McpPanel) is not None)

        # ---- 补全面板 ----
        palette.update_filter("/")
        await pilot.pause()
        check("输入 / 弹出面板", palette.visible)
        check("列出全部命令", len(palette._items) > 5, str(len(palette._items)))

        palette.update_filter("/re")
        await pilot.pause()
        check("过滤 /re 有结果",
              len(palette._items) >= 1 and palette._items[0].name == "resume",
              str([c.name for c in palette._items]))

        palette.update_filter("/zzz")
        await pilot.pause()
        check("无匹配时隐藏", not palette.visible)

        palette.update_filter("你好")
        await pilot.pause()
        check("非斜杠输入不弹面板", not palette.visible)

        # ---- 命令执行 ----
        agent = app._agent
        agent.history = [
            {"role": "user", "content": "测试消息一"},
            {"role": "assistant", "content": "回答一"},
        ]

        app._run_command("/help")
        await pilot.pause()
        text = conv_text(conv)
        check("/help 有输出", "可用命令" in text, text[-200:])
        check("/help 含 /new", "/new" in text)
        check("/help 含 /resume", "/resume" in text)

        app._run_command("/save")
        await pilot.pause()
        text = conv_text(conv)
        check("/save 有反馈", "已保存会话" in text, text[-150:])
        check("确实生成了会话 id", agent.session_id is not None)

        app._run_command("/context")
        await pilot.pause()
        text = conv_text(conv)
        check("/context 有用量信息", "上下文用量" in text, text[-300:])
        check("/context 有窗口信息", "窗口" in text)

        app._run_command("/tools")
        await pilot.pause()
        text = conv_text(conv)
        check("/tools 列出工具", "可用工具" in text)

        app._run_command("/skills")
        await pilot.pause()
        text = conv_text(conv)
        check("/skills 有输出", "技能" in text)

        app._run_command("/mcp")
        await pilot.pause()
        text = conv_text(conv)
        check("/mcp 有输出", "MCP" in text, text[-200:])

        app._run_command("/nonexist")
        await pilot.pause()
        text = conv_text(conv)
        check("未知命令有提示", "未知命令" in text)

        # ---- /new ----
        before_id = agent.session_id
        app._run_command("/new")
        await pilot.pause()
        text = conv_text(conv)
        check("/new 提示已成新会话", "已开始新会话" in text, text[-200:])
        check("/new 自动保存了旧会话", "已把上一个会话保存" in text, text[-250:])
        check("/new 后历史被清（只剩 AGENTS.md 或空）",
              len(agent.history) <= 2, str(len(agent.history)))

        # ---- /resume ----
        sessions = agent.list_sessions()
        check("有历史会话可选", len(sessions) >= 1, str(len(sessions)))

        app.do_resume()
        await pilot.pause()
        from tui.session_picker import SessionPicker

        check("弹出会话选择器", isinstance(app.screen, SessionPicker),
              type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause()
        check("Esc 关闭选择器", not isinstance(app.screen, SessionPicker))

        # ---- MCP 面板三态 ----
        panel = sidebar.query_one(McpPanel)
        sidebar.mcp_loading()
        await pilot.pause()
        check("MCP 显示加载中", panel.state == "loading")

        sidebar.mcp_update([("TestMCP", ["tool1", "tool2"], None)])
        await pilot.pause()
        check("MCP 显示已就绪", panel.state == "ready")
        check("MCP 记录了服务器", len(panel.servers) == 1)

        sidebar.mcp_update([("BadMCP", [], "连接超时")])
        await pilot.pause()
        check("MCP 能显示错误", panel.servers[0][2] == "连接超时")

        sidebar.mcp_disabled()
        await pilot.pause()
        check("MCP 能显示已关闭", panel.state == "disabled")

    # ---- 首次运行对话框 ----
    app2 = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)
    async with app2.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        from tui.app import FirstRunDialog

        app2.push_screen(FirstRunDialog("C:/tmp/config.ini"))
        await pilot.pause()
        check("首次运行对话框能弹出",
              isinstance(app2.screen, FirstRunDialog), type(app2.screen).__name__)
        await pilot.press("escape")
        await pilot.pause()
        check("对话框能关闭", not isinstance(app2.screen, FirstRunDialog))

    # ---- 退出保存询问 ----
    from tui.exit_dialog import ExitSaveDialog

    app3 = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)
    async with app3.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        conv = app3.query_one(Conversation)
        sidebar = app3.query_one(Sidebar)

        # 空会话退出：不问，直接走
        check("空会话没有未保存内容", app3._agent.has_unsaved() is False)
        check("空会话轮数为 0", app3._agent.turn_count() == 0)

        # 聊一轮后有了未保存内容
        conv.add_user("你好")
        app3._agent.history.append({"role": "user", "content": "你好"})
        app3._agent.history.append({"role": "assistant", "content": "在"})
        check("聊过一轮后有未保存内容", app3._agent.has_unsaved() is True)
        check("轮数按历史算出来是 1", app3._agent.turn_count() == 1)

        # Ctrl+C 空闲时应该弹询问框（不是直接退出）
        app3.action_interrupt_or_quit()
        await pilot.pause()
        check("空闲 Ctrl+C 弹出保存询问",
              isinstance(app3.screen, ExitSaveDialog), type(app3.screen).__name__)
        check("弹询问时程序没退出", app3.is_running)

        # Esc 取消，回到界面
        await pilot.press("escape")
        await pilot.pause()
        check("Esc 取消退出", not isinstance(app3.screen, ExitSaveDialog))
        check("取消后仍留在界面", app3.is_running)
        check("取消后历史还在", len(app3._agent.history) == 2)

        # 选保存：落盘 + 退出
        before = len(app3._agent.list_sessions())
        app3.request_exit()
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        after = len(app3._agent.list_sessions())
        check("选保存后真的存了盘", after == before + 1,
              "%d -> %d" % (before, after))
        check("存盘后拿到了会话 id", app3._agent.session_id is not None)
        check("存盘后没有未保存内容", app3._agent.has_unsaved() is False)

    # ---- 侧边栏轮数不会被 MCP 刷新冲掉 ----
    app4 = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)
    async with app4.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        sb = app4.query_one(Sidebar)
        app4._agent.history.append({"role": "user", "content": "一"})
        app4._agent.history.append({"role": "assistant", "content": "二"})
        app4._sync_turns()
        await pilot.pause()
        check("同步后侧边栏显示 1 轮", sb._turns == 1, str(sb._turns))

        # 模拟 MCP 异步连完触发的 setup
        app4._on_mcp_connected(_FakeMcp())
        await pilot.pause()
        check("MCP 刷新后轮数没被清零", sb._turns == 1, str(sb._turns))

    # ---- /clear 要清历史 ----
    app5 = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)
    async with app5.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        app5._agent.history.append({"role": "user", "content": "要被清掉的"})
        app5._agent.history.append({"role": "assistant", "content": "好"})
        app5._run_command("/clear")
        await pilot.pause()

        from tui.confirm import ConfirmDialog

        check("有历史时 /clear 先确认",
              isinstance(app5.screen, ConfirmDialog), type(app5.screen).__name__)
        await pilot.press("escape")
        await pilot.pause()
        check("取消后历史还在", len(app5._agent.history) == 2,
              str(len(app5._agent.history)))

        app5._run_command("/clear")
        await pilot.pause()
        app5.screen.query_one("#confirm-ok").press()
        await pilot.pause()
        check("/clear 真的清了历史", app5._agent.history == [],
              str(len(app5._agent.history)))
        check("/clear 后轮数归零", app5.query_one(Sidebar)._turns == 0)

    shutil.rmtree(ROOT, ignore_errors=True)

    print()
    print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
    if failed:
        for f in failed:
            print("  失败:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
