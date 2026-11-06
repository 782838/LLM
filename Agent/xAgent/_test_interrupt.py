"""中断与插话测试。"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.llm.client import Delta

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


print("=" * 70)
print("一、Client.stream 支持 should_stop")
print("=" * 70)

from core.config import Config
from core.llm.client import Client

# 用 mock 服务端模拟慢速流
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class SlowHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        # 发 50 个分片，每片间隔 0.05 秒
        for i in range(50):
            chunk = {"choices": [{"delta": {"content": str(i) + " "}}]}
            try:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.05)
        try:
            self.wfile.write(b"data: [DONE]\n\n")
        except Exception:
            pass


srv = HTTPServer(("127.0.0.1", 0), SlowHandler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = Config("http://127.0.0.1:%d/v1" % port, "mock")
cl = Client(cfg)

# 不中断：应该收到全部分片
pieces = 0
for d in cl.stream([{"role": "user", "content": "hi"}]):
    if d.content:
        pieces += 1
check("不中断时收完整个流", pieces == 50, str(pieces))

# 中断：只收到一部分
stop_flag = {"v": False}
pieces2 = 0


def should_stop():
    return stop_flag["v"]


for d in cl.stream([{"role": "user", "content": "hi"}], should_stop=should_stop):
    if d.content:
        pieces2 += 1
        if pieces2 == 5:
            stop_flag["v"] = True

check("中断后提前退出", pieces2 == 5, str(pieces2))
check("确实比不中断时少", pieces2 < pieces, "%d < %d" % (pieces2, pieces))

srv.shutdown()

print()
print("=" * 70)
print("二、Agent 中断语义")
print("=" * 70)

from core.agent import Agent

# 再造一个慢速服务
srv2 = HTTPServer(("127.0.0.1", 0), SlowHandler)
port2 = srv2.server_address[1]
threading.Thread(target=srv2.serve_forever, daemon=True).start()

cfg2 = Config("http://127.0.0.1:%d/v1" % port2, "mock")
agent = Agent(config=cfg2, auto_load_skills=False, auto_load_mcp=False)

# 后台线程在 0.5 秒后请求中断
def stopper():
    time.sleep(0.5)
    agent.request_stop()

threading.Thread(target=stopper, daemon=True).start()

t0 = time.time()
answer = agent.ask("给我说点什么")
elapsed = time.time() - t0

check("中断后 ask 会返回", isinstance(answer, str))
check("返回已生成的部分", len(answer) > 0, str(len(answer)))
check("没那么快说完（证明提前退出）", elapsed < 2.5, "%.2f 秒" % elapsed)
check("标记了 interrupted", agent.interrupted is True)

# 中断后历史里保留了部分回答
has_partial = any(
    "被用户中断" in str(m.get("content") or "")
    for m in agent.history if m.get("role") == "assistant"
)
check("历史里标注了中断", has_partial, str(len(agent.history)))

srv2.shutdown()

print()
print("=" * 70)
print("三、中断后能继续对话")
print("=" * 70)

# 用一个即时返回的服务
class QuickHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunk = {"choices": [{"delta": {"content": "好的"}}]}
        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


srv3 = HTTPServer(("127.0.0.1", 0), QuickHandler)
port3 = srv3.server_address[1]
threading.Thread(target=srv3.serve_forever, daemon=True).start()

agent2 = Agent(config=Config("http://127.0.0.1:%d/v1" % port3, "mock"),
               auto_load_skills=False, auto_load_mcp=False)
agent2.request_stop()          # 先设一个残留的中断标记
answer2 = agent2.ask("测试")
check("新提问会清掉旧的停止标记", not agent2._stopped())
check("中断标记复位", agent2.interrupted is False)
check("能正常拿到回答", answer2 == "好的", repr(answer2))

srv3.shutdown()

print()
print("=" * 70)
print("四、TUI 停止按钮与 Ctrl+C")
print("=" * 70)

from tui.app import XAgentApp
from tui.widgets import Conversation


class FakeAgent(Agent):
    def __init__(self):
        super().__init__(auto_load_skills=False, auto_load_mcp=False)

    def ask(self, text):
        return "假回答"


async def ui_test():
    app = XAgentApp(agent=FakeAgent(), skip_bootstrap=True)

    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()

        from textual.widgets import Button

        btn = app.query_one("#stop-btn", Button)
        check("存在停止按钮", btn is not None)
        check("默认隐藏", btn.display is False)

        # 模拟进入忙碌态
        app._busy = True
        app._show_stop_button(True)
        await pilot.pause()
        check("忙碌时按钮显示", btn.display is True)

        # 点按钮应该发出中断请求
        app._agent.clear_stop()
        btn.press()
        await pilot.pause()
        check("点按钮设置了停止标记", app._agent._stopped())

        # 结束一轮后按钮隐藏
        app._busy = False
        app._show_stop_button(False)
        await pilot.pause()
        check("结束后按钮隐藏", btn.display is False)

        # Ctrl+C 在忙碌时是中断
        app._busy = True
        app._agent.clear_stop()
        app.action_interrupt_or_quit()
        await pilot.pause()
        check("忙碌时 Ctrl+C 触发中断", app._agent._stopped())
        check("忙碌时 Ctrl+C 不退出", app.is_running)

        app._busy = False
        app._agent.clear_stop()

    return


asyncio.run(ui_test())

print()
print("=" * 70)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
