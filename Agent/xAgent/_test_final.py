"""最终阶段功能测试：配置化、首次生成、会话、命令、MCP 侧边栏、AGENTS.md。"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import agents_md
from core import bootstrap
from core import session as session_mod
from core import settings as settings_mod
from core.config import Config
from core.agent import Agent

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


SB = tempfile.mkdtemp(prefix="finaltest_")

print("=" * 72)
print("一、配置化：settings 读取与默认值")
print("=" * 72)

st = settings_mod.Settings()
# 没有配置文件时全用默认值
st.load("/nonexistent/config.ini")
check("无配置时用默认值", st.max_tool_rounds == 12, str(st.max_tool_rounds))
check("无配置时 warn_ratio 默认", abs(st.warn_ratio - 0.6) < 0.01, str(st.warn_ratio))
check("无配置时 cli_timeout 默认", st.cli_timeout == 30, str(st.cli_timeout))
check("无配置时 mcp_enabled 默认 True", st.mcp_enabled is True)

# 有配置文件时读配置
CFG = os.path.join(SB, "config.ini")
with open(CFG, "w", encoding="utf-8", newline="\n") as f:
    f.write(
        "base_url = http://x/v1\n"
        "model = m\n"
        "[agent]\n"
        "max_tool_rounds = 5\n"
        "[tools]\n"
        "cli_timeout = 99\n"
        "[mcp]\n"
        "enabled = false\n"
        "[context]\n"
        "warn_ratio = 0.8\n"
    )

st2 = settings_mod.Settings()
st2.load(CFG)
check("读到自定义 max_tool_rounds", st2.max_tool_rounds == 5, str(st2.max_tool_rounds))
check("读到自定义 cli_timeout", st2.cli_timeout == 99, str(st2.cli_timeout))
check("bool 解析 false", st2.mcp_enabled is False, str(st2.mcp_enabled))
check("float 解析", abs(st2.warn_ratio - 0.8) < 0.01, str(st2.warn_ratio))
check("未配的项仍用默认", st2.office_timeout == 60, str(st2.office_timeout))

# 非法值不崩
with open(CFG, "w", encoding="utf-8", newline="\n") as f:
    f.write("base_url = http://x/v1\nmodel = m\n[agent]\nmax_tool_rounds = 不是数字\n")

st3 = settings_mod.Settings()
st3.load(CFG)
check("非法值退回默认", st3.max_tool_rounds == 12, str(st3.max_tool_rounds))

print()
print("=" * 72)
print("二、首次运行生成配置")
print("=" * 72)

EMPTY = tempfile.mkdtemp(prefix="noconf_")
res = bootstrap.ensure_config(EMPTY)
check("没有配置时生成", res.created is True, str(res))
check("生成的文件存在", os.path.isfile(res.path), str(res.path))
check("需要重启提示", res.needs_restart is True)

content = open(res.path, encoding="utf-8").read()
check("模板含 base_url", "base_url = " in content)
check("模板含 [agent]", "[agent]" in content)
check("模板含 [context]", "[context]" in content)
check("模板含 [mcp]", "[mcp]" in content)
check("模板含 mock 模型名", "your-model-name" in content)
check("模板含 mock key", "sk-your-key-here" in content)

# 已有配置时不重复生成
res2 = bootstrap.ensure_config(EMPTY)
check("已有配置时不再生成", res2.created is False, str(res2))
check("返回已有路径", res2.path and os.path.isfile(res2.path))

shutil.rmtree(EMPTY, ignore_errors=True)

print()
print("=" * 72)
print("三、会话保存 / 列表 / 恢复")
print("=" * 72)

SROOT = tempfile.mkdtemp(prefix="sessroot_")
os.makedirs(os.path.join(SROOT, ".agents", "skills"), exist_ok=True)

MSGS = [
    {"role": "user", "content": "帮我做个 PPT"},
    {"role": "assistant", "content": "好的，三页够吗"},
    {"role": "user", "content": "够了"},
]

sid, path, err = session_mod.save(SROOT, MSGS, model="test-model")
check("保存成功", err is None and sid, str(err))
check("文件生成", os.path.isfile(path))
check("id 格式对", len(sid) == 15 and sid[8] == "-", sid)

data = json.load(open(path, encoding="utf-8"))
check("存了 messages", len(data["messages"]) == 3)
check("存了 model", data["model"] == "test-model")
check("存了 turns", data["turns"] == 2, str(data["turns"]))
check("存了 preview", "PPT" in data["preview"], data["preview"])
check("存了时间戳", data.get("created") and data.get("updated"))

listed = session_mod.list_all(SROOT)
check("能列出会话", len(listed) == 1, str(len(listed)))
check("列表带摘要", "PPT" in listed[0].preview, listed[0].preview)
check("列表带轮数", listed[0].turns == 2, str(listed[0].turns))

loaded, err = session_mod.load(SROOT, sid)
check("能读回会话", err is None and len(loaded["messages"]) == 3, str(err))

bad, err2 = session_mod.load(SROOT, "99999999-999999")
check("读不存在的会话报错", bad is None and "找不到" in (err2 or ""), str(err2))

ok, err3 = session_mod.delete(SROOT, sid)
check("能删会话", ok, str(err3))
check("删完列表空", session_mod.list_all(SROOT) == [])

print()
print("=" * 72)
print("四、AGENTS.md 一次注入")
print("=" * 72)

AROOT = tempfile.mkdtemp(prefix="agentsmd_")
os.makedirs(os.path.join(AROOT, ".agents", "skills"), exist_ok=True)

# 没有文件
info = agents_md.read(AROOT)
check("没有 AGENTS.md 时 found=False", info.found is False)

# 有文件
md_path = os.path.join(AROOT, agents_md.AGENTS_FILE)
with open(md_path, "w", encoding="utf-8", newline="\n") as f:
    f.write("# 项目说明\n\n这个项目用 Python 3.13。\n不要用 git commit。\n")

info = agents_md.read(AROOT)
check("找到 AGENTS.md", info.found is True)
check("读到内容", "Python 3.13" in info.content)
check("没截断", info.truncated is False)

history = []
ok, note = agents_md.inject(history, AROOT)
check("注入成功", ok, note)
check("注入了两条消息", len(history) == 2, str(len(history)))
check("第一条是 user", history[0]["role"] == "user")
check("带标记前缀", history[0]["content"].startswith(agents_md.MARKER))
check("含文件内容", "Python 3.13" in history[0]["content"])
check("第二条是 assistant 确认", history[1]["role"] == "assistant")

# 重复注入要跳过
ok2, note2 = agents_md.inject(history, AROOT)
check("重复注入被跳过", not ok2, note2)
check("历史条数没变", len(history) == 2, str(len(history)))

# already_injected
check("能识别已注入", agents_md.already_injected(history) is True)
check("空历史识别为未注入", agents_md.already_injected([]) is False)

# 超长截断
with open(md_path, "w", encoding="utf-8", newline="\n") as f:
    f.write("x" * 50000)
info2 = agents_md.read(AROOT, max_chars=1000)
check("超长被截断", info2.truncated is True)
check("截断后长度受限", len(info2.content) <= 1000, str(len(info2.content)))

shutil.rmtree(AROOT, ignore_errors=True)

print()
print("=" * 72)
print("五、命令定义")
print("=" * 72)

from tui import commands as cmd_mod

for name in ("new", "resume", "save", "quit", "compact", "help"):
    check("有 /%s 命令" % name, cmd_mod.resolve("/" + name) is not None)

check("别名 /n 指向 new", cmd_mod.resolve("/n").name == "new")
check("别名 /q 指向 quit", cmd_mod.resolve("/q").name == "quit")
check("别名 /c 指向 compact", cmd_mod.resolve("/c").name == "compact")
check("未知命令返回 None", cmd_mod.resolve("/nonexist") is None)

# 补全
all_cmds = cmd_mod.suggest("/")
check("空输入给全部命令", len(all_cmds) == len(cmd_mod.COMMANDS), str(len(all_cmds)))

sub = cmd_mod.suggest("/re")
check("前缀过滤生效", len(sub) >= 1 and any(c.name == "resume" for c in sub),
      str([c.name for c in sub]))

sub2 = cmd_mod.suggest("/zzz")
check("无匹配返回空", sub2 == [], str(len(sub2)))

help_txt = cmd_mod.help_text()
check("帮助含全部命令", all(c.text in help_txt for c in cmd_mod.COMMANDS))
check("帮助含快捷键提示", "Ctrl+M" in help_txt)

print()
print("=" * 72)
print("六、Agent 接线")
print("=" * 72)

AG_ROOT = tempfile.mkdtemp(prefix="agentroot_")
os.makedirs(os.path.join(AG_ROOT, ".agents", "skills"), exist_ok=True)

with open(os.path.join(AG_ROOT, agents_md.AGENTS_FILE), "w",
          encoding="utf-8", newline="\n") as f:
    f.write("# 测试项目\n用中文回答。\n")

cfg = Config("http://127.0.0.1:1/v1", "test")
a = Agent(config=cfg, auto_load_skills=False, auto_load_mcp=False,
          skills_root=AG_ROOT)

ok, note = a.start_session()
check("Agent 开新会话注入 AGENTS.md", ok, note)
check("历史已有注入消息", len(a.history) == 2, str(len(a.history)))
check("记录了 agents_md_content", a.agents_md_content is not None)

a.history.append({"role": "user", "content": "你好"})
a.history.append({"role": "assistant", "content": "你好"})

sid2, detail = a.save_session()
check("Agent 能保存会话", sid2 is not None, str(detail))
check("保存后记录了 session_id", a.session_id == sid2)

a.reset()
check("reset 清空历史", a.history == [])
check("reset 也清了 session_id", a.session_id is None)

ok3, note3 = a.resume_session(sid2)
check("能恢复会话", ok3, note3)
check("恢复后有历史", len(a.history) >= 4, str(len(a.history)))
check("恢复了 agents_md", a.agents_md_content is not None)

# 恢复的会话再开新会话时，AGENTS.md 不会重复注入
first_len = len(a.history)
check("恢复的历史里已有注入标记", agents_md.already_injected(a.history))

shutil.rmtree(AG_ROOT, ignore_errors=True)
shutil.rmtree(SROOT, ignore_errors=True)
shutil.rmtree(SB, ignore_errors=True)

print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
