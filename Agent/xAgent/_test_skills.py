"""Skill 机制测试：逐条对照作业四步要求。

用临时目录造技能树，不依赖仓库里真实的 .agents，也不改动工作目录太久。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")

from core import skills as S
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


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ------------------------------------------------------------ 造测试项目
SANDBOX = tempfile.mkdtemp(prefix="skilltest_")
ORIGINAL_CWD = os.getcwd()

SKILLS = os.path.join(SANDBOX, ".agents", "skills")

write(
    os.path.join(SKILLS, "notice", "SKILL.md"),
    """---
name: 撰写通知
description: 撰写公司内部通知
---
# 正文
标题必须带部门名。
""",
)

write(
    os.path.join(SKILLS, "zodiac", "SKILL.md"),
    """---
name: 星座运势解读
description: 根据星座给出运势
---
# 星座
参考 references/rules.md。
""",
)
write(os.path.join(SKILLS, "zodiac", "references", "rules.md"), "# 详细规则\n幸运色对照表……")

# 同名文件，测试多候选
write(os.path.join(SKILLS, "zodiac", "references", "dup.md"), "第一处 dup")
write(os.path.join(SKILLS, "zodiac", "ref2", "dup.md"), "第二处 dup")

# 有目录没 SKILL.md
os.makedirs(os.path.join(SKILLS, "empty_skill"), exist_ok=True)

# 缺 description
write(
    os.path.join(SKILLS, "broken", "SKILL.md"),
    "---\nname: 坏技能\n---\n正文\n",
)

# 缺 name
write(
    os.path.join(SKILLS, "noname", "SKILL.md"),
    "---\ndescription: 没名字\n---\n正文\n",
)

# 非技能目录里的干扰文件
write(os.path.join(SKILLS, "readme.txt"), "这不是技能")

os.chdir(SANDBOX)

print("=" * 72)
print("第 1 步：Skill 发现与注册")
print("=" * 72)

check("项目根是 cwd", S.project_root() == os.path.abspath(SANDBOX), S.project_root())
check("技能目录是 cwd 下的 .agents/skills",
      S.skills_dir() == os.path.join(os.path.abspath(SANDBOX), ".agents", "skills"),
      S.skills_dir())

found, notes = S.discover()
names = [s.name for s in found]
check("发现 2 个有效技能", len(found) == 2, str(names))
check(" recognises notice", "撰写通知" in names, str(names))
check("recognises zodiac", "星座运势解读" in names, str(names))
check("缺 description 的被跳过", "坏技能" not in names, str(names))
check("缺 name 的被跳过", all(n for n in names), str(names))
check("无 SKILL.md 的目录被跳过且记提示",
      any("empty_skill" in n for n in notes), str(notes))
check("提示里说明缺字段",
      any("description" in n for n in notes) and any("name" in n for n in notes), str(notes))

# 初始化只读元数据：正文里的标记不该出现在 Skill 对象里
notice = [s for s in found if s.name == "撰写通知"][0]
check("Skill 对象不含正文字段", not hasattr(notice, "body"))
check("Skill 记录 SKILL.md 路径", os.path.isfile(notice.skill_md), notice.skill_md)
check("Skill 记录目录", os.path.isdir(notice.directory), notice.directory)

# 目录不存在时返回空
check("目录不存在返回空列表", S.discover("/no/such/root")[0] == [])

print()
print("=" * 72)
print("第 2 步：注入 System Prompt")
print("=" * 72)

sp = S.build_system_prompt(found)
check("含引导语", "You have access to the following skills" in sp, sp[:80])
check("含技能名 1", "`撰写通知`" in sp)
check("含技能名 2", "`星座运势解读`" in sp)
check("含描述", "撰写公司内部通知" in sp)
check("含 loadSkill 提示", "`loadSkill`" in sp)
check("格式是 名称: 描述", "- `撰写通知`: 撰写公司内部通知." in sp, sp)

# 正文绝不能进 System Prompt
check("System Prompt 不含正文内容", "标题必须带部门名" not in sp, sp)
check("System Prompt 不含附件名", "rules.md" not in sp, sp)

# 无技能时
check("无技能返回空串", S.build_system_prompt([]) == "")

# 有基础 prompt 时拼接
combo = S.build_system_prompt(found, base_prompt="你是助手。")
check("基础 prompt 保留在前", combo.startswith("你是助手。"), combo[:30])
check("技能块在后", "You have access" in combo)

print()
print("=" * 72)
print("第 3 步：loadSkill 工具")
print("=" * 72)

# 只给 name
r = S.load_skill(name="撰写通知", skills=found)
check("只给 name 返回全文", "标题必须带部门名" in r, r[:120])
check("返回内容含 frontmatter", "name: 撰写通知" in r, r[:120])

# 缺 name
r = S.load_skill(skills=found)
check("缺 name 报错", "缺少 name" in r, r[:80])

# 技能不存在
r = S.load_skill(name="没有这个", skills=found)
check("技能不存在时报错并列出可用", "找不到" in r and "撰写通知" in r, r[:130])

# 给 filename
r = S.load_skill(name="星座运势解读", filename="references/rules.md", skills=found)
check("技能相对路径能读", "详细规则" in r, r[:120])
check("给 filename 时不重复返回 SKILL.md", "参考 references" not in r, r[:200])

# 只给文件名，递归搜索
r = S.load_skill(name="星座运势解读", filename="rules.md", skills=found)
check("只给文件名能递归找到", "详细规则" in r, r[:120])

# 项目相对路径
rel = os.path.join(".agents", "skills", "zodiac", "references", "rules.md")
r = S.load_skill(name="星座运势解读", filename=rel, skills=found)
check("项目相对路径能读", "详细规则" in r, r[:120])

# 绝对路径
abs_path = os.path.join(SKILLS, "zodiac", "references", "rules.md")
r = S.load_skill(name="星座运势解读", filename=abs_path, skills=found)
check("绝对路径能读", "详细规则" in r, r[:120])

# 同名多候选
r = S.load_skill(name="星座运势解读", filename="dup.md", skills=found)
check("多候选时返回列表", "多个" in r and "dup.md" in r, r[:250])
check("列出候选路径", r.count("dup.md") >= 2, r[:300])

# 越权
r = S.load_skill(name="星座运势解读", filename="../../../etc/passwd", skills=found)
check("越权路径被拒绝", "超出技能目录" in r or "已拒绝" in r, r[:150])

r = S.load_skill(name="星座运势解读", filename="../../notice/SKILL.md", skills=found)
check("跨技能目录被拒绝", "超出技能目录" in r, r[:150])

# 不存在的文件
r = S.load_skill(name="星座运势解读", filename="nope.md", skills=found)
check("文件不存在有提示", "找不到" in r, r[:130])

print()
print("=" * 72)
print("第 4 步：动态加载原则 + 与已有工具协作")
print("=" * 72)

reg = default_registry(skills=found, skills_root=SANDBOX)
check("工具数是 16", len(reg) == 16, str(len(reg)))
check("有 loadSkill", "loadSkill" in reg)
check("原有工具都在", all(
    n in reg for n in ["RunCli", "readFile", "searchWeb", "fetchWeb", "getDate", "isLeapYear"]
), reg.describe())

# 通过注册表调用 loadSkill
r, err = reg.execute("loadSkill", {"name": "撰写通知"})
check("注册表能调 loadSkill", err is None and "标题必须带部门名" in (r or ""), str(err))

r, err = reg.execute("loadSkill", {"name": "星座运势解读", "filename": "rules.md"})
check("注册表能带 filename 调用", err is None and "详细规则" in (r or ""), str(err))

# 工具声明
schema = [s for s in reg.schemas() if s["function"]["name"] == "loadSkill"][0]
props = schema["function"]["parameters"]["properties"]
check("loadSkill 有 name 参数", "name" in props)
check("loadSkill 有 filename 参数", "filename" in props)
check("name 是必需", schema["function"]["parameters"]["required"] == ["name"],
      str(schema["function"]["parameters"]["required"]))

# 正文只在调用时才进上下文
r = S.load_skill(name="撰写通知", skills=found)
check("调用后才拿得到正文", "标题必须带部门名" in r)

print()
print("=" * 72)
print("额外：Agent 接线")
print("=" * 72)

from core.agent import Agent

agent = Agent(auto_load_skills=True, skills_root=SANDBOX)
check("Agent 自动发现技能", len(agent.skills) == 2, str(len(agent.skills)))
check("Agent 的 system_prompt 含技能清单",
      "You have access to the following skills" in agent.system_prompt)
check("Agent 的 system_prompt 不含正文",
      "标题必须带部门名" not in agent.system_prompt)
check("Agent 的工具有 loadSkill", "loadSkill" in agent.tools)
check("messages() 带上 system 消息",
      agent.messages() and agent.messages()[0]["role"] == "system",
      str(agent.messages()[:1]))

agent2 = Agent(auto_load_skills=False)
check("可关闭自动加载", agent2.skills == [] and agent2.system_prompt == "")

print()
print("=" * 72)

# 清理
os.chdir(ORIGINAL_CWD)
shutil.rmtree(SANDBOX, ignore_errors=True)
print("沙箱已清理:", not os.path.exists(SANDBOX))

print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
