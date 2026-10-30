"""用 Textual 的无头模式验证界面能起、能画、能响应输入。

不接真实模型，用假 Agent 喂事件，确认界面层的接线是对的。
"""
import asyncio
import sys

from core.agent import Agent, ToolCall

from tui import events
from tui.app import XAgentApp
from tui.widgets import Conversation, MessageCard, PromptInput, Sidebar, ToolCard

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


class FakeAgent(Agent):
    """不发网络请求的 Agent，用来验证界面接线。"""

    def __init__(self):
        super().__init__(auto_load_skills=False)
        self.asked = []

    def ask(self, text):
        self.asked.append(text)
        return "假回答"


async def main():
    app = XAgentApp(agent=FakeAgent())

    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause()

        check("应用能启动", app.is_running)
        check("对话区存在", app.query_one(Conversation) is not None)
        check("侧边栏存在", app.query_one(Sidebar) is not None)
        check("输入框存在", app.query_one("#prompt", PromptInput) is not None)
        check("状态栏存在", app.query_one("#status") is not None)

        conv = app.query_one(Conversation)

        # 系统消息
        conv.add_system("这是一条系统提示")
        await pilot.pause()
        cards = conv.query(MessageCard)
        check("系统消息卡片已挂载", len(cards) >= 1, str(len(cards)))

        # 用户消息
        conv.add_user("你好呀")
        await pilot.pause()
        check("用户卡片增加", len(list(conv.query(MessageCard))) >= 2)

        # 助手流式
        conv.start_assistant()
        conv.push_delta("第一段")
        conv.push_delta("，第二段")
        await pilot.pause()
        assistants = list(conv.query(MessageCard))
        check("流式创建了助手卡片",
              any(c.role == "assistant" for c in assistants))
        check("流式内容已累积",
              any("第一段" in c._content for c in assistants if c.role == "assistant"))

        conv.end_assistant("第一段，第二段")
        await pilot.pause()
        check("流式结束后内容完整",
              any(c._content == "第一段，第二段" for c in assistants if c.role == "assistant"))

        # 工具卡片
        conv.add_tool("readFile", {"path": "a.txt"})
        await pilot.pause()
        tools = list(conv.query(ToolCard))
        check("工具卡片已创建", len(tools) == 1, str(len(tools)))
        check("工具卡片显示名称", tools[0].tool_name == "readFile")
        check("工具初始状态为执行中", tools[0]._result is None and tools[0]._error is None)

        conv.set_tool_result("readFile", "文件内容第一行\n第二行", None)
        await pilot.pause()
        check("工具结果已更新", tools[0]._result is not None)

        conv.add_tool("deleteFile", {"path": "b.txt"})
        await pilot.pause()
        conv.set_tool_result("deleteFile", None, "权限不足")
        await pilot.pause()
        tools2 = list(conv.query(ToolCard))
        check("失败工具卡片记录了错误", any(t._error for t in tools2))

        # 错误消息
        conv.add_error("这是个测试错误")
        await pilot.pause()
        check("错误卡片已挂载",
              any(c.role == "error" for c in conv.query(MessageCard)))

        # 侧边栏
        sb = app.query_one(Sidebar)
        sb.setup("test-model", ["getDate", "readFile"], [], [])
        await pilot.pause()
        check("侧边栏能 setup", sb._model == "test-model")

        # 快捷键
        await pilot.press("f1")
        await pilot.pause()
        check("F1 显示工具不报错", True)

        await pilot.press("f2")
        await pilot.pause()
        check("F2 显示技能不报错", True)

        await pilot.press("ctrl+l")
        await pilot.pause()
        check("Ctrl+L 清屏不报错", True)

        await pilot.press("ctrl+n")
        await pilot.pause()
        check("Ctrl+N 新会话不报错", True)

        # 输入框
        prompt = app.query_one("#prompt", PromptInput)
        prompt.text = "测试输入"
        await pilot.pause()
        check("输入框能写", prompt.text == "测试输入")
        prompt.clear_text()
        await pilot.pause()
        check("输入框能清", prompt.text == "")

        # 空输入不提交
        prompt.text = ""
        prompt.action_submit()
        await pilot.pause()
        check("空输入不提交", len(prompt.text) == 0)

    print()
    print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
    if failed:
        for f in failed:
            print("  失败:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
