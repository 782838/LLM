"""Office 工具测试：officeDoc 与 officeHelp。

会真实调用 officecli 生成文件到临时目录，测完清理。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")

from core.tools import default_registry
from core.tools import office_tools as OT

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


SANDBOX = tempfile.mkdtemp(prefix="officetest_")
reg = default_registry()


def run(args, timeout=90):
    return reg.execute("officeDoc", {"args": args, "timeout": timeout})


print("=" * 70)
print("一、可用性")
print("=" * 70)

check("能在默认路径找到 officecli", OT.find_officecli() is not None, str(OT.find_officecli()))
check("officeDoc 已注册", "officeDoc" in reg)
check("officeHelp 已注册", "officeHelp" in reg)
check("工具总数 19", len(reg) == 19, str(len(reg)))

print()
print("=" * 70)
print("二、参数校验")
print("=" * 70)

r, err = reg.execute("officeDoc", {})
check("缺 args 有提示", "缺少 args 参数" in (r or ""), (r or "")[:80])

r, _ = reg.execute("officeDoc", {"args": "create a.pptx"})
check("传字符串而非数组被拒", "必须是字符串数组" in (r or ""), (r or "")[:80])

r, _ = reg.execute("officeDoc", {"args": {"cmd": "x"}})
check("传字典被拒", "必须是字符串数组" in (r or ""), (r or "")[:80])

print()
print("=" * 70)
print("三、PPT 生成")
print("=" * 70)

PPT = os.path.join(SANDBOX, "deck.pptx")
r, e = run(["create", PPT])
check("create 成功", e is None and "退出码：0" in (r or ""), (r or "")[:100])
check("文件已生成", os.path.isfile(PPT))

r, _ = run(["add", PPT, "/", "--type", "slide", "--prop", "title=季度汇报"])
check("加第 1 页成功", "退出码：0" in (r or ""), (r or "")[:100])

r, _ = run(["add", PPT, "/", "--type", "slide", "--prop", "title=数据"])
check("加第 2 页成功", "退出码：0" in (r or ""), (r or "")[:100])

r, _ = run(["add", PPT, "/slide[2]", "--type", "shape",
            "--prop", "text=增长 25%", "--prop", "x=2cm", "--prop", "y=4cm"])
check("加文本框成功", "退出码：0" in (r or ""), (r or "")[:120])

r, _ = run(["view", PPT, "outline"])
check("view outline 成功", "退出码：0" in (r or ""))
check("outline 显示 2 页", "2 slide" in (r or ""), (r or "")[:200])

# 用 python-pptx 独立验证
try:
    from pptx import Presentation
    prs = Presentation(PPT)
    check("PPT 确实是 2 页", len(prs.slides) == 2, str(len(prs.slides)))
    texts = []
    for s in prs.slides:
        texts += [sh.text_frame.text for sh in s.shapes if sh.has_text_frame]
    check("PPT 含标题文字", any("季度汇报" in t for t in texts), str(texts))
    check("PPT 含正文文字", any("增长 25%" in t for t in texts), str(texts))
except ImportError:
    check("python-pptx 可用", False, "未安装")

print()
print("=" * 70)
print("四、Word 生成")
print("=" * 70)

DOC = os.path.join(SANDBOX, "report.docx")
r, e = run(["create", DOC])
check("create 成功", e is None and os.path.isfile(DOC), (r or "")[:100])

r, _ = run(["add", DOC, "/body", "--type", "paragraph",
            "--prop", "text=执行摘要", "--prop", "style=Heading1"])
check("加标题段成功", "退出码：0" in (r or ""), (r or "")[:120])

r, _ = run(["add", DOC, "/body", "--type", "paragraph",
            "--prop", "text=本季度营收增长 25%。"])
check("加正文段成功", "退出码：0" in (r or ""), (r or "")[:120])

try:
    from docx import Document
    doc = Document(DOC)
    check("Word 有 2 段", len(doc.paragraphs) == 2, str(len(doc.paragraphs)))
    check("第一段是 Heading",
          doc.paragraphs[0].style.name.startswith("Heading"), doc.paragraphs[0].style.name)
    check("第一段文字正确", doc.paragraphs[0].text == "执行摘要", doc.paragraphs[0].text)
    check("第二段文字正确", "25%" in doc.paragraphs[1].text, doc.paragraphs[1].text)
except ImportError:
    check("python-docx 可用", False, "未安装")

print()
print("=" * 70)
print("五、Excel 生成")
print("=" * 70)

XLS = os.path.join(SANDBOX, "data.xlsx")
r, e = run(["create", XLS])
check("create 成功", e is None and os.path.isfile(XLS), (r or "")[:100])

r, _ = run(["set", XLS, "/Sheet1/A1", "--prop", "value=姓名", "--prop", "bold=true"])
check("写 A1 成功", "退出码：0" in (r or ""), (r or "")[:120])

r, _ = run(["set", XLS, "/Sheet1/B1", "--prop", "value=金额"])
check("写 B1 成功", "退出码：0" in (r or ""), (r or "")[:120])

r, _ = run(["get", XLS, "/Sheet1/A1", "--json"])
check("get 能读回 A1", "姓名" in (r or ""), (r or "")[:200])
check("get 返回 JSON", '"success": true' in (r or ""), (r or "")[:100])
check("读回带 bold 属性", '"font.bold": true' in (r or ""), (r or "")[:300])

print()
print("=" * 70)
print("六、officeHelp")
print("=" * 70)

r, e = reg.execute("officeHelp", {})
check("查全部命令成功", e is None and r and len(r) > 100, str(e))
check("帮助含 create 命令", "create" in (r or ""), (r or "")[:200])

r, _ = reg.execute("officeHelp", {"topic": "docx"})
check("查 docx 元素成功", r and "paragraph" in (r or "").lower(), (r or "")[:200])

r, _ = reg.execute("officeHelp", {"topic": "pptx slide"})
check("查 pptx slide 成功", r and len(r) > 50, (r or "")[:200])

print()
print("=" * 70)
print("七、错误处理")
print("=" * 70)

r, e = run(["view", os.path.join(SANDBOX, "nope.docx"), "outline"])
check("不存在的文件返回非 0", "退出码：1" in (r or "") or "退出码：2" in (r or ""), (r or "")[:150])
check("错误时有说明", "执行失败" in (r or ""), (r or "")[:200])

r, _ = run(["create", os.path.join(SANDBOX, "bad.xyz")])
check("不支持的扩展名会报错", "执行失败" in (r or "") or "退出码：" in (r or ""), (r or "")[:150])

print()
print("=" * 70)
print("八、工具声明")
print("=" * 70)

schemas = {s["function"]["name"]: s for s in reg.schemas()}
doc_schema = schemas["officeDoc"]["function"]
help_schema = schemas["officeHelp"]["function"]

check("officeDoc 有 args 参数", "args" in doc_schema["parameters"]["properties"])
check("args 是数组",
      doc_schema["parameters"]["properties"]["args"]["type"] == "array",
      str(doc_schema["parameters"]["properties"]["args"].get("type")))
check("args 元素是字符串",
      doc_schema["parameters"]["properties"]["args"]["items"]["type"] == "string")
check("args 必需", doc_schema["parameters"]["required"] == ["args"],
      str(doc_schema["parameters"]["required"]))
check("有 timeout 参数", "timeout" in doc_schema["parameters"]["properties"])
check("description 提到 officecli", "officecli" in doc_schema["description"])
check("description 提到先查 help", "officeHelp" in doc_schema["description"])
check("officeHelp 有 topic 参数", "topic" in help_schema["parameters"]["properties"])
check("officeHelp 不强制 topic", help_schema["parameters"]["required"] == [],
      str(help_schema["parameters"]["required"]))

shutil.rmtree(SANDBOX, ignore_errors=True)
print()
print("沙箱已清理:", not os.path.exists(SANDBOX))

print()
print("=" * 70)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
