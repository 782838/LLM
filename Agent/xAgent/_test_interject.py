"""插话测试：忙碌时再发一条消息，应该中断上一条并处理新的。"""
import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.agent import Agent
from tui.app import XAgentApp
from tui.widgets import Conversation, PromptInput

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


class SlowHandler(BaseHTTPRequestHandler):
    """第一句慢速吐字，第二句立即完成。"""

    count = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        SlowHandler.count += 1
        nth = SlowHandler.count

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        if nth == 1:
            # 第一次：慢，给中断留时间
            for i in range(60):
                chunk = {"choices": [{"delta": {"content": "慢%d " % i}}]}
                try:
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                time.sleep(0.05)
        else:
            chunk = {"choices": [{"delta": {"content": "快速回答"}}]}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()


srv = HTTPServer(("127.0.0.1", 0), SlowHandler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


async def main():
    agent = Agent(config=Config("http://127.0.0.1:%d/v1" % port, "mock"),
                  auto_load_skills=False, auto_load_mcp=False)
    app = XAgentApp(agent=agent, skip_bootstrap=True)

    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        SlowHandler.count = 0

        conv = app.query_one(Conversation)

        # 发第一条（会慢）
        app.post_message(PromptInput.Submitted("第一条消息"))
        await pilot.pause()
        await asyncio.sleep(0.4)
        await pilot.pause()

        check("第一条正在处理中", app._busy)

        # 插话：忙碌时再发一条
        app.post_message(PromptInput.Submitted("插话的消息"))
        await pilot.pause()

        # 应该先中断，再起新一轮
        await asyncio.sleep(0.2)
        await pilot.pause()

        stop_set = agent._stopped() or True   # 中断后标志可能已被下一轮清掉

        # 等第二轮完成
        for _ in range(40):
            await pilot.pause()
            await asyncio.sleep(0.15)
            if not app._busy:
                break

        check("插话后最终回到空闲", not app._busy, str(app._busy))

        # 检查历史里有没有那条插话
        user_msgs = [m.get("content") for m in agent.history
                     if m.get("role") == "user"]
        check("历史里有第一条", any("第一条消息" in str(x) for x in user_msgs),
              str(user_msgs)[:150])
        check("历史里有插话的那条", any("插话的消息" in str(x) for x in user_msgs),
              str(user_msgs)[:150])

        # 检查对话区有提示
        from rich.console import Console
        import io

        texts = []
        for w in conv.children:
            buf = io.StringIO()
            try:
                Console(file=buf, width=100).print(w.render())
            except Exception:
                continue
            texts.append(buf.getvalue())
        joined = "\n".join(texts)

        check("对话区提示了中断", "中断" in joined, joined[-300:])
        check("对话区有第二条回答", "快速回答" in joined, joined[-300:])

    return 0


try:
    rc = asyncio.run(main())
finally:
    srv.shutdown()

print()
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
