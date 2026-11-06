"""上下文压缩与历史检索测试。

覆盖八条要求：
    1. /compact 手动触发（逻辑层，不含界面）
    2. 上下文监控与阈值
    3. 原始上下文归档
    4. 压缩 Prompt
    5. 摘要替换 + 归档说明
    6. recallContext 工具
    7. 与现有工具共存
    8. 用量显示文案
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")

from core import context as C
from core.tools import default_registry

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


SB = tempfile.mkdtemp(prefix="ctxtest_")

HISTORY = [
    {"role": "user", "content": "帮我做一份季度汇报 PPT"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "officeDoc",
                      "arguments": '{"args":["create","deck.pptx"]}'}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "已创建 deck.pptx"},
    {"role": "assistant", "content": "PPT 建好了，共 3 页"},
    {"role": "user", "content": "把第二页标题改成「营收情况」"},
]

print("=" * 72)
print("一、token 估算与用量（第 2、8 条）")
print("=" * 72)

check("空文本 0 token", C.estimate_tokens("") == 0)
check("非空文本至少 1", C.estimate_tokens("a") >= 1)
check("中文估算合理", 5 <= C.estimate_tokens("一二三四五六七八九十") <= 30,
      str(C.estimate_tokens("一二三四五六七八九十")))

u = C.Usage(12000, 131072, True)
check("百分比计算正确", abs(u.percent - 9.16) < 0.1, "%.2f" % u.percent)
check("低用量不警告", not u.should_warn)
check("显示带「默认」标记", "默认" in u.summary(), u.summary())
check("显示含 k 单位", "k" in u.summary(), u.summary())

u2 = C.Usage(80000, 131072, True)
check("超 60% 触发警告", u2.should_warn)

u3 = C.Usage(80000, 131072, False)
check("非默认时不显示「默认」", "默认" not in u3.summary(), u3.summary())

# 窗口解析
class FakeCfg:
    def __init__(self, w=None):
        self.context_window = w

w, is_def = C.resolve_window(FakeCfg(None))
check("没配置用默认 128k", w == 128 * 1024 and is_def, "%s %s" % (w, is_def))

w, is_def = C.resolve_window(FakeCfg(32000))
check("配置了就用配置值", w == 32000 and not is_def, "%s %s" % (w, is_def))

w, is_def = C.resolve_window(FakeCfg("abc"))
check("配置非法时退回默认", w == 128 * 1024 and is_def)

# 历史 token
ht = C.history_tokens(HISTORY)
check("历史 token 大于 0", ht > 0, str(ht))
check("空历史 0 token", C.history_tokens([]) == 0)

# 真实 usage 优先
usage, hist = C.compute_usage("sys", HISTORY, 131072, True,
                              real_prompt_tokens=500, last_hist_tokens=0)
check("有真实 usage 时标记 exact", usage.exact)
check("有真实 usage 时以它为基准", usage.used >= 500, str(usage.used))

usage2, _ = C.compute_usage("sys", HISTORY, 131072, True)
check("没真实 usage 时是估算", not usage2.exact)

print()
print("=" * 72)
print("二、归档（第 3 条）")
print("=" * 72)

aid, path, err = C.archive(SB, HISTORY, now=None)
check("归档成功", err is None and aid, str(err))
check("编号格式正确", C.valid_archive_id(aid), aid)
check("文件已生成", os.path.isfile(path))

lines = open(path, encoding="utf-8").read().strip().splitlines()
check("每条消息一行", len(lines) == len(HISTORY), str(len(lines)))

first = json.loads(lines[0])
check("保留 role", first.get("role") == "user")
check("保留 content", "季度汇报" in (first.get("content") or ""))
check("有顺序号", "seq" in first)
check("有时间戳", "ts" in first)

second = json.loads(lines[1])
check("保留 tool_calls", "tool_calls" in second, str(list(second.keys())))
check("工具参数完整",
      "deck.pptx" in json.dumps(second.get("tool_calls"), ensure_ascii=False))

third = json.loads(lines[2])
check("保留 tool_call_id", third.get("tool_call_id") == "c1", str(third.get("tool_call_id")))

# 空历史
aid2, path2, err2 = C.archive(SB, [])
check("空历史不归档", aid2 is None and err2)

# 归档目录不存在时能建
SB2 = tempfile.mkdtemp(prefix="ctxtest2_")
aid3, path3, err3 = C.archive(SB2, HISTORY, archive_id="20200101-120000")
check("能自动建目录", err3 is None and os.path.isfile(path3))
check("能用指定编号", aid3 == "20200101-120000", aid3)

# 列出归档
archives = C.list_archives(SB)
check("能列出归档", len(archives) >= 1, str(len(archives)))
check("列出时带消息数", archives[0][3] == len(HISTORY), str(archives[0][3]))

# 读回来
msgs = C.read_archive(aid, SB)
check("能读回归档", len(msgs) == len(HISTORY), str(len(msgs)))
check("读回的 role 对", msgs[0].get("role") == "user")

check("非法编号读不到", C.read_archive("bad-id", SB) == [])
check("不存在的归档读不到", C.read_archive("20200101-000001", SB) == [])

print()
print("=" * 72)
print("三、压缩 Prompt（第 4 条）")
print("=" * 72)

check("Prompt 含角色说明", "上下文管理助手" in C.COMPACT_PROMPT)
check("Prompt 含 5000 token 要求", "5,000" in C.COMPACT_PROMPT)
check("Prompt 含六项要点", all(
    k in C.COMPACT_PROMPT for k in
    ["用户目标与要求", "已经完成的工作", "当前工作状态",
     "关键技术信息", "关键决策与原因", "下一步任务"]))
check("Prompt 提到 recallContext", "recallContext" in C.COMPACT_PROMPT)
check("Prompt 要求 Markdown", "Markdown" in C.COMPACT_PROMPT)

msgs = C.build_compact_messages(HISTORY, system_prompt="你是助手")
check("压缩请求带 system", msgs[0]["role"] == "system")
check("压缩请求末条是 user", msgs[-1]["role"] == "user")
check("历史内容被带上", "deck.pptx" in msgs[-1]["content"])
check("工具调用也被带上", "officeDoc" in msgs[-1]["content"])
check("工具返回也被带上", "已创建 deck.pptx" in msgs[-1]["content"])
check("带自适应长度说明", "补充说明" in msgs[-1]["content"])

# 短原文的目标长度不能超过原文
short_h = [{"role": "user", "content": "短问题"},
           {"role": "assistant", "content": "短回答"}]
short_msg = C.build_compact_messages(short_h)[-1]["content"]
check("短原文给精简提示", "很短" in short_msg or "几十个" in short_msg,
      short_msg[short_msg.find("补充说明"):][:80])

# 摘要校验
check("空摘要被拒", not C.validate_summary("")[0])
check("太短被拒", not C.validate_summary("短")[0])
check("错误信息被拒",
      not C.validate_summary("error: something went wrong here")[0])
ok, _ = C.validate_summary("# 摘要\n" + "内容" * 200)
check("正常摘要通过", ok)

# 摘要比原文长时被拒（避免压缩倒挂）
long_summary = "# 摘要\n" + "内容" * 200
ok, reason = C.validate_summary(long_summary, original_tokens=10)
check("摘要比原文长时被拒", not ok, str(ok))
check("拒绝原因说明没意义", "没有意义" in (reason or ""), (reason or "")[:60])

ok, _ = C.validate_summary(long_summary, original_tokens=100000)
check("摘要明显短于原文时通过", ok)

print()
print("=" * 72)
print("四、摘要替换（第 5 条）")
print("=" * 72)

summary = "# 用户目标\n帮用户做季度汇报 PPT，已完成 3 页。"
new_h = C.build_compacted_history(summary, aid)

check("替换后是 2 条", len(new_h) == 2, str(len(new_h)))
check("user/assistant 交替", [m["role"] for m in new_h] == ["user", "assistant"])
check("摘要内容在内", "季度汇报 PPT" in new_h[0]["content"])
check("归档说明已追加", aid in new_h[0]["content"])
check("说明提到 recallContext", "recallContext" in new_h[0]["content"])
check("说明含时间", "此前上下文已于" in new_h[0]["content"])

note = C.archive_note(aid, when="2026-10-22 15:30:00")
check("归档说明格式对", "2026-10-22 15:30:00" in note and aid in note, note)

# 压缩后 token 应显著减小
before_k = C.estimate_tokens(C.build_compact_messages(HISTORY)[-1]["content"])
after_k = C.estimate_tokens(new_h[0]["content"])
check("压缩后 token 减少", after_k < before_k, "%d -> %d" % (before_k, after_k))

print()
print("=" * 72)
print("五、recallContext 检索（第 6 条）")
print("=" * 72)

r, e = C.recall("deck.pptx", root=SB)
check("按关键词能搜到", e is None and "deck.pptx" in (r or ""), (e or "")[:80])
check("结果带归档编号", aid in (r or ""), (r or "")[:100])
check("结果带消息位置", "第" in (r or "") and "条" in (r or ""), (r or "")[:100])

r, e = C.recall("营收", root=SB)
check("搜中文关键词", e is None and "营收" in (r or ""), (e or "")[:80])

r, e = C.recall("deck", archive_id=aid, root=SB)
check("指定归档检索", e is None and "deck" in (r or ""))
check("只搜指定归档", aid in (r or ""))

r, e = C.recall("deck", archive_id="20200101-000000", root=SB)
check("归档不存在时报错", r is None and "找不到" in (e or ""), (e or "")[:80])
check("报错时列出可用归档", aid in (e or ""), (e or "")[:120])

r, e = C.recall("", root=SB)
check("空关键词报错", r is None and "缺少" in (e or ""))

r, e = C.recall("绝对不存在的内容xyz", root=SB)
check("搜不到时给出提示", "没有找到" in (r or ""), (r or "")[:80])

r, e = C.recall("bad-id-format", archive_id="111", root=SB)
check("非法编号格式报错", r is None and "格式" in (e or ""), (e or "")[:80])

# 空目录
EMPTY = tempfile.mkdtemp(prefix="empty_")
r, e = C.recall("x", root=EMPTY)
check("没有归档时提示", r is None and "还没有" in (e or ""), (e or "")[:100])
shutil.rmtree(EMPTY, ignore_errors=True)

# 长度控制
r, e = C.recall("a", root=SB, max_chars=50)
check("超长结果被截断", "上限" in (r or "") or len(r or "") < 400, str(len(r or "")))

print()
print("=" * 72)
print("六、与现有工具共存（第 7 条）")
print("=" * 72)

REG_ROOT = tempfile.mkdtemp(prefix="regroot_")
reg = default_registry(skills_root=REG_ROOT)
check("recallContext 已注册", "recallContext" in reg)
check("工具总数 20", len(reg) == 20, str(len(reg)))
check("原有工具都在", all(
    n in reg for n in ["RunCli", "officeDoc", "loadSkill", "createSkill",
                       "searchWeb", "fetchWeb", "getDate"]
), reg.describe()[:120])

# 通过注册表调用
C.archive(REG_ROOT, HISTORY)
res, err = reg.execute("recallContext", {"text": "deck.pptx"})
check("注册表能调 recallContext",
      err is None and "deck.pptx" in (res or ""), str(err)[:100])

res, err = reg.execute("recallContext", {})
check("缺 text 时报错", "缺少" in (res or ""), (res or "")[:80])

# 工具声明
schema = [s for s in reg.schemas() if s["function"]["name"] == "recallContext"][0]
props = schema["function"]["parameters"]["properties"]
check("有 id 参数", "id" in props)
check("有 text 参数", "text" in props)
check("只要求 text", schema["function"]["parameters"]["required"] == ["text"],
      str(schema["function"]["parameters"]["required"]))

shutil.rmtree(REG_ROOT, ignore_errors=True)
shutil.rmtree(SB, ignore_errors=True)
shutil.rmtree(SB2, ignore_errors=True)

print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
