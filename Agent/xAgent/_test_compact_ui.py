"""验证 TUI 层的 /compact 拦截、输入限制、对比浮层。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import context as C
from core.agent import Agent
from tui.app import XAgentApp
from tui.compact_view import CompactView
from tui.widgets import Conversation

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
        self.compact_called = False

    def ask(self, text):
        return "假回答"

    def compact(self, on_event=None):
        self.compact_called = True
        if on_event:
            on_event("archiving")
            on_event("summarizing")
            result = {
                "archive_id": "20260101-000000",
                "archive_path": "x.jsonl",
                "before": "【user】\n原始内容在这里",
                "after": "【上下文摘要】\n摘要内容在这里",
                "summary": "# 摘要",
                "before_tokens": 10000,
                "after_tokens": 2000,
            }
            on_event("done", result)
            return True, result
        return False, "no"


async def main():
    # ---- 1. /compact 走命令分支，不当提示词发出去 ----
    agent = FakeAgent()
    app = XAgentApp(agent=agent, skip_bootstrap=True)

    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()

        # 太短的对话直接拒绝
        app.post_message(
            __import__("tui.widgets", fromlist=["PromptInput"]).PromptInput.Submitted("/compact")
        )
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()

        conv = app.query_one(Conversation)
        from rich.console import Console
        import io

        texts = []
        for w in conv.children:
            buf = io.StringIO()
            Console(file=buf, width=100).print(w.render())
            texts.append(buf.getvalue())
        joined = "\n".join(texts)

        check("短对话提示不需要压缩",
              "不需要压缩" in joined or "不会有收益" in joined,
              joined[-200:])
        check("没有真的调 compact", not agent.compact_called)

        # ---- 2. 未知命令 ----
        app.post_message(
            __import__("tui.widgets", fromlist=["PromptInput"]).PromptInput.Submitted("/foo")
        )
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        texts2 = []
        for w in conv.children:
            buf = io.StringIO()
            Console(file=buf, width=100).print(w.render())
            texts2.append(buf.getvalue())
        check("未知命令有提示", "未知命令" in "\n".join(texts2))

    # ---- 3. 足够长时能压缩，并弹出对比面板 ----
    agent2 = FakeAgent()
    agent2.history = []

    app2 = XAgentApp(agent=agent2, skip_bootstrap=True)
    async with app2.run_test(size=(110, 34)) as pilot:
        await pilot.pause()

        # on_mount 里 start_session 会 reset 历史，所以等它跑完再塞数据
        agent2.history = [
            {"role": "user", "content": "问题" * 300},
            {"role": "assistant", "content": "回答" * 300},
            {"role": "user", "content": "追问" * 300},
            {"role": "assistant", "content": "再答" * 300},
        ]

        print("历史 token:", C.history_tokens(agent2.history))

        app2.post_message(
            __import__("tui.widgets", fromlist=["PromptInput"]).PromptInput.Submitted("/compact")
        )

        for _ in range(40):
            await pilot.pause()
            await asyncio.sleep(0.25)
            if isinstance(app2.screen, CompactView):
                break

        check("压缩被调用", agent2.compact_called)
        check("弹出对比面板", isinstance(app2.screen, CompactView),
              type(app2.screen).__name__)

        if isinstance(app2.screen, CompactView):
            view = app2.screen
            check("面板含归档编号", "20260101-000000" in str(view.result.get("archive_id")),
                  str(view.result.get("archive_id")))
            check("面板有前后内容",
                  "原始内容" in view.result.get("before", "")
                  and "摘要内容" in view.result.get("after", ""))

            # 关闭
            await pilot.press("escape")
            await pilot.pause()
            check("Esc 能关面板", not isinstance(app2.screen, CompactView))

    # ---- 4. 输入限制：超阈值时拒绝普通输入 ----
    # 60% of 128k ≈ 78.6k tokens，需要足够大的历史才能触发
    agent3 = FakeAgent()
    agent3.history = [
        {"role": "user", "content": "内容" * 70000},
    ]
    usage = agent3.context_usage()
    print()
    print("撑爆后的用量:", usage.summary())

    ok, reason = agent3.can_accept_input()
    check("超阈值时拒绝输入", not ok, str(ok))
    check("拒绝理由提示 /compact", "/compact" in (reason or ""), (reason or "")[:100])

    # 正在压缩时也拒绝
    agent3.history = []
    agent3.compacting = True
    ok2, reason2 = agent3.can_accept_input()
    check("压缩中拒绝输入", not ok2, str(ok2))
    check("压缩中的理由正确", "压缩" in (reason2 or ""), (reason2 or "")[:60])

    import shutil

    shutil.rmtree(ROOT, ignore_errors=True)
    print()
    print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
    if failed:
        for f in failed:
            print("  失败:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
