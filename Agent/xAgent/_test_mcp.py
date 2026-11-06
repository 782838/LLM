"""MCP Client 测试。

分两部分：
    一、纯本地逻辑（配置解析、名字映射、结果归一化）—— 不联网
    二、真实连接（可选）—— 有 .mcp.json 且地址可用时才跑
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")

from core.mcp import adapter, config as mcp_config
from core.mcp.manager import McpManager
from core.mcp.runner import AsyncRunner

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


SANDBOX = tempfile.mkdtemp(prefix="mcptest_")


def write(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


print("=" * 72)
print("一、配置解析")
print("=" * 72)

# 没有配置文件
servers, notes = mcp_config.load(SANDBOX)
check("没有 .mcp.json 时返回空", servers == [] and notes == [], str(servers))

# 正常配置
write(os.path.join(SANDBOX, ".mcp.json"), {
    "mcpServers": {
        "srv-http": {"type": "streamable_http", "url": "http://127.0.0.1:8090/mcp"},
        "srv-stdio": {"type": "stdio", "command": "python", "args": ["s.py"]},
        "srv-nostype": {"url": "http://x/mcp"},
    }
})
servers, notes = mcp_config.load(SANDBOX)
check("解析出 3 个 Server", len(servers) == 3, str(len(servers)))
names = [s.name for s in servers]
check("名字都拿到", set(names) == {"srv-http", "srv-stdio", "srv-nostype"}, str(names))

http_srv = [s for s in servers if s.name == "srv-http"][0]
check("HTTP 类型识别", http_srv.is_http)
check("URL 正确", http_srv.url == "http://127.0.0.1:8090/mcp", http_srv.url)

stdio_srv = [s for s in servers if s.name == "srv-stdio"][0]
check("stdio 类型识别", stdio_srv.is_stdio)
check("command 正确", stdio_srv.command == "python")
check("args 正确", stdio_srv.args == ["s.py"], str(stdio_srv.args))

nostype = [s for s in servers if s.name == "srv-nostype"][0]
check("没写 type 时按 url 推断为 HTTP", nostype.is_http, nostype.type)

# 连字符写法也支持
write(os.path.join(SANDBOX, ".mcp.json"), {
    "mcpServers": {"a": {"type": "streamable-http", "url": "http://x/mcp"}}
})
servers, _ = mcp_config.load(SANDBOX)
check("支持 streamable-http 连字符写法",
      len(servers) == 1 and servers[0].is_http, str(servers))

# 各种错误配置
bad_cases = [
    ("缺 url", {"mcpServers": {"x": {"type": "streamable_http"}}}),
    ("url 协议不对", {"mcpServers": {"x": {"type": "streamable_http", "url": "ftp://a"}}}),
    ("stdio 缺 command", {"mcpServers": {"x": {"type": "stdio"}}}),
    ("不支持的 type", {"mcpServers": {"x": {"type": "websocket", "url": "http://a"}}}),
    ("缺 mcpServers", {"foo": {}}),
]
for label, cfg in bad_cases:
    write(os.path.join(SANDBOX, ".mcp.json"), cfg)
    try:
        s, n = mcp_config.load(SANDBOX)
        rejected = (len(s) == 0 and len(n) > 0)
    except mcp_config.McpConfigError:
        rejected = True
    check("拒绝%s" % label, rejected)

# 非法 JSON
with open(os.path.join(SANDBOX, ".mcp.json"), "w", encoding="utf-8") as f:
    f.write("{ bad json")
try:
    mcp_config.load(SANDBOX)
    check("非法 JSON 抛错", False)
except mcp_config.McpConfigError:
    check("非法 JSON 抛错", True)

print()
print("=" * 72)
print("二、工具名映射")
print("=" * 72)

check("生成前缀名",
      adapter.exposed_name("Bazi-MCP", "getBazi") == "Bazi-MCP__getBazi",
      adapter.exposed_name("Bazi-MCP", "getBazi"))

s, t = adapter.split_name("Bazi-MCP__getBazi")
check("反查服务器名", s == "Bazi-MCP", str(s))
check("反查工具名", t == "getBazi", str(t))

s, t = adapter.split_name("noPrefix")
check("无前缀时返回 None", s is None and t == "noPrefix", str((s, t)))

# 不同 Server 的同名工具不冲突
n1 = adapter.exposed_name("A", "tool")
n2 = adapter.exposed_name("B", "tool")
check("不同 Server 同名工具不冲突", n1 != n2, "%s vs %s" % (n1, n2))

print()
print("=" * 72)
print("三、Schema 规整")
print("=" * 72)

s1 = adapter.sanitize_schema(None)
check("None schema 补成空对象", s1 == {"type": "object", "properties": {}}, str(s1))

s2 = adapter.sanitize_schema({"type": "object", "properties": {"a": {"type": "string"}}})
check("object schema 原样保留", s2["properties"]["a"]["type"] == "string", str(s2))

s3 = adapter.sanitize_schema({"type": "string"})
check("非 object 包一层", s3["type"] == "object" and "value" in s3["properties"], str(s3))

print()
print("=" * 72)
print("四、结果归一化")
print("=" * 72)


class FakeText:
    type = "text"
    def __init__(self, text):
        self.text = text


class FakeImage:
    type = "image"
    mime_type = "image/png"
    def __init__(self, data):
        self.data = data


class FakeResult:
    def __init__(self, content, structured=None, is_error=False):
        self.content = content
        self.structured_content = structured
        self.is_error = is_error


text, err = adapter.normalize_result(FakeResult([FakeText("你好")]))
check("纯文本正常返回", text == "你好" and err is None, str((text, err)))

text, err = adapter.normalize_result(FakeResult([]))
check("空内容有提示", "空" in (text or ""), str(text))

text, err = adapter.normalize_result(FakeResult([FakeText("出错啦")], is_error=True))
check("is_error 转成错误", text is None and "出错啦" in (err or ""), str((text, err)))

text, err = adapter.normalize_result(FakeResult([FakeImage("x" * 1000)]))
check("图片有占位说明", "图片" in (text or "") and "1000" in (text or ""), (text or "")[:80])

text, err = adapter.normalize_result(
    FakeResult([FakeText("文本")], structured={"k": "v"}))
check("结构化数据被附加", "结构化" in (text or "") and '"k"' in (text or ""), (text or "")[:120])

text, err = adapter.normalize_result(
    FakeResult([FakeText("A"), FakeText("B")]))
check("多段文本拼接", "A" in text and "B" in text, text)

print()
print("=" * 72)
print("五、后台事件循环")
print("=" * 72)

runner = AsyncRunner()
runner.start()
check("Runner 能启动", runner.running)


async def add(a, b):
    return a + b


result = runner.run(add(2, 3))
check("同步调用 async 函数", result == 5, str(result))


async def boom():
    raise ValueError("故意失败")


try:
    runner.run(boom())
    check("异步异常能传回同步侧", False)
except ValueError as e:
    check("异步异常能传回同步侧", "故意失败" in str(e), str(e))

runner.close()
check("Runner 能关闭", not runner.running)


async def _make_coro():
    """现造一个协程，避免创建后不适配警告。"""
    return add(1, 1)


# 关闭后再用应该报错
try:
    coro = _make_coro()
    try:
        runner.run(coro)
        check("关闭后拒绝执行", False)
    finally:
        coro.close()      # 没被跑掉就手动关，避免 RuntimeWarning
except Exception:
    check("关闭后拒绝执行", True)

print()
print("=" * 72)
print("六、故障隔离")
print("=" * 72)

# 配一个连不上的地址，确认不抛异常、不影响其他
BROKEN = tempfile.mkdtemp(prefix="mcpbroken_")
write(os.path.join(BROKEN, ".mcp.json"), {
    "mcpServers": {
        "dead": {"type": "streamable_http", "url": "http://127.0.0.1:1/mcp"}
    }
})

mgr = McpManager(root=BROKEN)
try:
    mgr.connect_all()
    check("连不上不抛异常", True)
except Exception as e:
    check("连不上不抛异常", False, str(e))

check("失败的 Server 有记录", len(mgr.notes) > 0, str(mgr.notes)[:100])
check("会话列表为空", mgr.sessions == {}, str(mgr.sessions))
check("没有工具注册", mgr.tools == [])
check("status_lines 报告失败", any("失败" in l for l in mgr.status_lines()),
      str(mgr.status_lines()))

# 关键：连不上时本地工具仍然全部可用
from core.tools import default_registry
reg = default_registry(mcp_manager=mgr)
check("连不上时本地 20 个工具都在", len(reg) == 20, str(len(reg)))
check("RunCli 仍在", "RunCli" in reg)
check("officeDoc 仍在", "officeDoc" in reg)
r, e = reg.execute("isLeapYear", {"year": 2024})
check("本地工具能正常执行", e is None and "闰年" in (r or ""), str(e))

mgr.close()
shutil.rmtree(BROKEN, ignore_errors=True)

print()
print("=" * 72)
print("七、真实连接（有配置才跑）")
print("=" * 72)

LIVE_ROOT = r"D:\LLM\office"
live_cfg = mcp_config.find_config(LIVE_ROOT)
if not live_cfg:
    print("跳过：%s 下没有 .mcp.json" % LIVE_ROOT)
else:
    live = McpManager(root=LIVE_ROOT)
    live.connect_all()

    if live.sessions:
        check("至少连上一个 Server", len(live.sessions) >= 1, str(live.sessions))
        check("发现到工具", len(live.tools) > 0, str(len(live.tools)))
        check("工具名带前缀",
              all("__" in t.name for t in live.tools),
              str([t.name for t in live.tools])[:200])

        # 注册进真实 Registry
        live_reg = default_registry(mcp_manager=live)
        check("MCP 工具进了 Registry",
              len(live_reg) == 20 + len(live.tools),
              "%d vs 20+%d" % (len(live_reg), len(live.tools)))

        # 真实调用一个无必填参数的工具
        free_tools = [t for t in live.tools if not t.required]
        if free_tools:
            t = free_tools[0]
            text, err = t.call()
            check("真实调用成功（%s）" % t.name, err is None and text,
                  (err or str(text))[:150])
        else:
            print("  （没有无必填参数的工具，跳过真实调用）")

        # 通过 Registry 调用
        r, e = live_reg.execute("isLeapYear", {"year": 2024})
        check("MCP 注册后本地工具照常工作", e is None and "闰年" in (r or ""))
    else:
        print("跳过：没有连上的 Server")
        for n in live.notes:
            print("   ", n)

    live.close()

shutil.rmtree(SANDBOX, ignore_errors=True)
print()
print("沙箱已清理:", not os.path.exists(SANDBOX))

print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
