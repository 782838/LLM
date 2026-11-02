"""Agent Skills：发现技能、注入 System Prompt、按需加载正文。

规范要点
--------
1. 项目根是**程序启动时的用户工作目录**（os.getcwd()），
   不是 python.exe 的安装目录，也不是本代码所在目录。
   技能放在 <项目根>/.agents/skills/<技能名>/SKILL.md

2. 初始化阶段**只读 name 和 description**，不读正文。
   正文只有模型调用 loadSkill 时才进入对话上下文。

3. SKILL.md 开头用 YAML Frontmatter 声明，name 和 description 是必需字段：

       ---
       name: 撰写通知
       description: 撰写公司内部通知
       ---
       正文规则……

4. loadSkill 的读取范围严格限制在该技能目录内部，
   防止 ../ 之类的路径解析错误读到别处文件。

5. createSkill 让模型能自己建技能。技能名只允许小写字母、数字和连字符，
   这条规则同时管住了格式规范和路径穿越两件事。
"""
import os
import re

SKILL_FILE = "SKILL.md"
SKILLS_DIRNAME = os.path.join(".agents", "skills")

# 单个文件的读取上限，避免技能里放了个大文件把上下文撑爆
MAX_FILE_CHARS = 30000


class SkillError(Exception):
    """技能文件不合法。"""


class Skill:
    """一个已发现的技能。初始化阶段只填 name / description / 路径。"""

    def __init__(self, name, description, skill_md, directory):
        self.name = name
        self.description = description
        self.skill_md = skill_md      # SKILL.md 的绝对路径
        self.directory = directory    # 该技能目录的绝对路径

    def __repr__(self):
        return "Skill(%r)" % self.name


# ---------------------------------------------------------------- YAML 头部

def parse_frontmatter(text):
    """拆出 YAML 头部和正文，返回 (头部字典, 正文)。

    头部用 --- 包围。没有头部时返回 ({}, 全文)。
    """
    stripped = text.lstrip("\ufeff")
    if not stripped.startswith("---"):
        return {}, stripped

    lines = stripped.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        # 只有开头没有结尾，当作没有头部
        return {}, stripped

    head = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])

    try:
        import yaml
    except ImportError:
        return _manual_frontmatter(head), body

    try:
        data = yaml.safe_load(head) or {}
    except Exception as e:
        raise SkillError("YAML 头部解析失败：%s" % e)
    if not isinstance(data, dict):
        raise SkillError("YAML 头部必须是一组键值对。")
    return data, body


def _manual_frontmatter(text):
    """没装 PyYAML 时的退路，只认 key: value 这种简单行。"""
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def read_meta(path):
    """只读 SKILL.md 的头部，不读正文。

    这是初始化阶段用的：正文可能很长，没必要一上来就读进内存。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    meta, _body = parse_frontmatter(text)

    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()

    if not name:
        raise SkillError("缺少 name 字段")
    if not description:
        raise SkillError("缺少 description 字段")

    return name, description


# ---------------------------------------------------------------- 发现技能

def project_root():
    """项目根 = 程序启动时的用户工作目录。

    这是作业明确要求的：不是 python.exe 安装目录，也不是代码存放目录。
    """
    return os.path.abspath(os.getcwd())


def skills_dir(root=None):
    """返回 <项目根>/.agents/skills 的绝对路径。"""
    return os.path.join(root or project_root(), SKILLS_DIRNAME)


def discover(root=None):
    """扫描 .agents/skills/，返回 (技能列表, 提示信息列表)。

    只读 name 和 description，不读正文。
    单个技能有问题不会中断整体加载，问题记进 notes。
    """
    notes = []
    base = skills_dir(root)

    if not os.path.isdir(base):
        return [], notes

    try:
        entries = sorted(os.listdir(base))
    except OSError as e:
        notes.append("读取技能目录失败：%s" % e)
        return [], notes

    skills = []
    seen = {}

    for entry in entries:
        folder = os.path.join(base, entry)
        if not os.path.isdir(folder):
            continue

        skill_md = os.path.join(folder, SKILL_FILE)
        if not os.path.isfile(skill_md):
            notes.append("跳过 %s：目录里没有 %s" % (entry, SKILL_FILE))
            continue

        try:
            name, description = read_meta(skill_md)
        except SkillError as e:
            notes.append("跳过 %s：%s" % (entry, e))
            continue
        except UnicodeDecodeError:
            notes.append("跳过 %s：文件不是 UTF-8 编码" % entry)
            continue
        except OSError as e:
            notes.append("跳过 %s：读取失败 %s" % (entry, e))
            continue

        if name in seen:
            notes.append(
                "跳过 %s：技能名「%s」与 %s 重复" % (entry, name, seen[name])
            )
            continue
        seen[name] = entry

        skills.append(Skill(name, description, skill_md, folder))

    return skills, notes


# ---------------------------------------------------------------- System Prompt

SYSTEM_PROMPT_HEADER = "You have access to the following skills:"
SYSTEM_PROMPT_FOOTER = (
    "Use the `loadSkill` tool to load the full instructions of a skill when needed. "
    "You can also load additional files referenced by a skill."
)


def build_system_prompt(skills, base_prompt=None):
    """把技能清单拼进 System Prompt。

    只放 name 和 description，不放正文 —— 正文靠 loadSkill 按需加载。
    """
    if not skills:
        return base_prompt or ""

    lines = [SYSTEM_PROMPT_HEADER]
    for skill in skills:
        desc = skill.description.strip().rstrip("。.")
        lines.append("- `%s`: %s." % (skill.name, desc))
    lines.append(SYSTEM_PROMPT_FOOTER)

    block = "\n".join(lines)

    if base_prompt:
        return base_prompt.rstrip() + "\n\n" + block
    return block


# ---------------------------------------------------------------- 路径安全

def _within(path, directory):
    """判断 path 是否在 directory 内部（含自身）。"""
    try:
        path = os.path.realpath(path)
        directory = os.path.realpath(directory)
    except OSError:
        return False
    return os.path.commonpath([path, directory]) == directory


def _resolve_in_skill(skill, filename):
    """把 filename 解析成技能目录内的真实路径。

    返回 (绝对路径, 越权错误, 未找到标记)。

    分两种情况：
        - 只是个文件名（不含路径分隔符）：交给递归搜索，不在这里判越权
        - 带路径：依次尝试技能相对、项目相对、绝对三种解释，
          只接受落在技能目录内的结果
    """
    has_sep = (os.sep in filename) or ("/" in filename) or os.path.isabs(filename)

    if not has_sep:
        # 纯文件名，交给 _search_by_name 处理
        return None, None, "需要按名称搜索"

    root = project_root()
    candidates = []

    if os.path.isabs(filename):
        candidates.append(filename)
    else:
        candidates.append(os.path.join(skill.directory, filename))
        candidates.append(os.path.join(root, filename))

    escaped = False
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if not _within(normalized, skill.directory):
            escaped = True
            continue
        if os.path.isfile(normalized):
            return normalized, None, None

    if escaped:
        return None, (
            "路径超出技能目录范围，已拒绝：%s。"
            "只能读取该技能目录内部的文件。" % filename
        ), None

    return None, None, "文件不存在"


def _search_by_name(skill, filename):
    """只给文件名时，在技能目录里递归搜索。

    返回 (匹配列表, 错误信息)。匹配多个时由调用方交给模型决定。
    """
    target = os.path.basename(filename)
    found = []

    for dirpath, dirnames, filenames in os.walk(skill.directory):
        dirnames.sort()
        for fname in sorted(filenames):
            if fname == target:
                found.append(os.path.normpath(os.path.join(dirpath, fname)))

    if not found:
        return [], "技能「%s」目录里找不到名为 %s 的文件。" % (skill.name, target)
    return found, None


# ---------------------------------------------------------------- loadSkill

def load_skill(name=None, filename=None, skills=None, root=None):
    """loadSkill 工具的实现。

    name      必需，技能名称
    filename  可选，附件文件的路径或名称

    只给 name 时返回 SKILL.md 全文；
    同时给 filename 时读取该附件，不重复返回 SKILL.md。
    """
    if not name or not str(name).strip():
        return "缺少 name 参数。请给出要加载的技能名称。"

    name = str(name).strip()

    if skills is None:
        skills, _notes = discover(root)

    by_name = {s.name: s for s in skills}
    skill = by_name.get(name)

    if skill is None:
        available = "、".join(by_name) if by_name else "（没有可用技能）"
        return "找不到名为「%s」的技能。当前可用技能：%s" % (name, available)

    # 没有 filename：返回 SKILL.md 全文
    if not filename or not str(filename).strip():
        try:
            with open(skill.skill_md, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            return "读取技能「%s」失败：%s" % (name, e)

        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS].rstrip() + "\n……（内容过长，已截断）"

        return "技能「%s」的完整说明：\n\n%s" % (name, text.strip())

    filename = str(filename).strip().strip('"').strip("'")

    # 有 filename：读附件
    path, err, not_found = _resolve_in_skill(skill, filename)

    if err:
        return "加载失败：%s" % err

    if path is None and not_found:
        # 精确路径没命中，退回到按文件名递归搜索
        matches, search_err = _search_by_name(skill, filename)

        if search_err:
            return search_err

        if len(matches) > 1:
            listing = "\n".join(
                "%d. %s" % (i, os.path.relpath(m, skill.directory).replace(os.sep, "/"))
                for i, m in enumerate(matches, 1)
            )
            return (
                "技能「%s」目录里有多个名为 %s 的文件，请指定要读哪一个（用 filename 传相对路径）：\n%s"
                % (name, os.path.basename(filename), listing)
            )

        path = matches[0]

    if not os.path.isfile(path):
        return "文件不存在：%s" % filename

    # 兜底再校验一次，防止符号链接之类的绕开
    if not _within(path, skill.directory):
        return "加载失败：路径超出技能目录范围，已拒绝。"

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return "读取失败：%s 不是 UTF-8 文本文件。" % filename
    except OSError as e:
        return "读取失败：%s" % e

    truncated = False
    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS].rstrip() + "\n……（内容过长，已截断）"
        truncated = True

    rel = os.path.relpath(path, skill.directory).replace(os.sep, "/")
    head = "技能「%s」的文件 %s：" % (name, rel)
    if truncated:
        head += "（已截断到 %d 字符）" % MAX_FILE_CHARS

    return head + "\n\n" + content.strip()


def describe(skills):
    """给界面显示的一句话摘要。"""
    if not skills:
        return "无技能"
    return "%d 个技能：%s" % (len(skills), "、".join(s.name for s in skills))


# ---------------------------------------------------------------- createSkill

# 技能名只能是「小写字母、数字、连字符」，这条规则同时满足格式要求和路径安全
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_NAME_LEN = 64


def validate_name(name):
    """校验技能名。返回 (规范化后的名字, 错误信息)。"""
    if not name or not str(name).strip():
        return None, "缺少 name 参数。请给出技能名称，只能用小写字母、数字和连字符。"

    raw = str(name).strip()

    if len(raw) > MAX_NAME_LEN:
        return None, "技能名太长（%d 字符），上限 %d。" % (len(raw), MAX_NAME_LEN)

    if not NAME_PATTERN.match(raw):
        return None, (
            "技能名「%s」不符合规范。只能用**小写字母、数字和连字符**，"
            "且必须以字母或数字开头，例如 my-skill、notice-v2。"
            "不能用大写、下划线、空格、中文，也不能含 / 或 .. 这类路径字符。" % raw
        )

    return raw, None


def validate_context(context):
    """校验 skillContext。返回 (解析出的元数据, 正文, 错误信息)。

    作业要求的四项：正确的 YAML Frontmatter、name、description、正文内容。
    """
    if not context or not str(context).strip():
        return None, None, (
            "缺少 skillContext 参数。请传入 SKILL.md 的完整内容，"
            "包括 YAML Frontmatter 和正文。"
        )

    text = str(context)

    if not text.lstrip("\ufeff").startswith("---"):
        return None, None, (
            "skillContext 缺少 YAML Frontmatter。"
            "文件必须以 --- 开头，头部声明 name 和 description，例如：\n\n"
            "---\nname: 示例技能\ndescription: 一句话说明用途\n---\n\n正文内容……"
        )

    try:
        meta, body = parse_frontmatter(text)
    except SkillError as e:
        return None, None, "skillContext 的 YAML 头部有问题：%s" % e

    if not meta:
        return None, None, (
            "skillContext 的 YAML 头部是空的，或者没有用 --- 正确闭合。"
            "头部至少要写 name 和 description。"
        )

    meta_name = str(meta.get("name") or "").strip()
    if not meta_name:
        return None, None, "skillContext 的 YAML 头部缺少 name 字段。"

    meta_desc = str(meta.get("description") or "").strip()
    if not meta_desc:
        return None, None, "skillContext 的 YAML 头部缺少 description 字段。"

    if not body.strip():
        return None, None, (
            "skillContext 只有 YAML 头部，没有正文。"
            "请在 --- 之后写上这个技能的具体规则。"
        )

    return meta, body, None


def create_skill(name=None, skill_context=None, root=None, skills=None):
    """createSkill 工具的实现。

    在 <项目根>/.agents/skills/<name>/ 下创建 SKILL.md。

    不覆盖已有技能；附件目录（references/ scripts/ 等）不归这里管，
    由模型继续调用 fileOps 工具完成。
    """
    # 1. 校验技能名
    safe_name, err = validate_name(name)
    if err:
        return err, None

    # 2. 校验内容
    meta, body, err = validate_context(skill_context)
    if err:
        return err, None

    base = skills_dir(root)
    target_dir = os.path.join(base, safe_name)
    target_file = os.path.join(target_dir, SKILL_FILE)

    # 3. 已存在就不动。先看目录，再看文件，覆盖两种情况
    if os.path.isdir(target_dir) or os.path.exists(target_file):
        return (
            "技能「%s」已经存在，没有覆盖。\n"
            "目录：%s\n"
            "如果确实要重建，请先调用 deleteDirectory 删掉它，或者换一个名字。"
            % (safe_name, target_dir)
        ), None

    # 4. 兜底校验路径没跑出技能根目录（正则已挡住，这里是双保险）
    if not _within(target_dir, base):
        return "拒绝创建：目标路径超出了技能目录范围。", None

    # 5. 写文件
    try:
        os.makedirs(target_dir, exist_ok=True)
        # 统一用 \n 换行，避免跨平台差异
        content = str(skill_context).replace("\r\n", "\n").lstrip("\ufeff")
        with open(target_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except OSError as e:
        return "创建技能失败：%s" % e, None

    # 6. 注册到内存里的技能列表，当前会话立刻可用
    skill = Skill(
        name=str(meta.get("name")).strip(),
        description=str(meta.get("description")).strip(),
        skill_md=target_file,
        directory=target_dir,
    )
    notes = []
    if skills is not None:
        exists = any(s.directory == target_dir for s in skills)
        if not exists:
            skills.append(skill)

    note = ""
    if meta.get("name") and str(meta.get("name")).strip() != safe_name:
        note = (
            "\n（目录名是 %s，YAML 里的显示名是「%s」，两者不一致，按现有惯例允许。）"
            % (safe_name, str(meta.get("name")).strip())
        )

    body_lines = len(body.strip().splitlines())
    return (
        "已创建技能「%s」。\n"
        "目录：%s\n"
        "文件：%s\n"
        "正文：%d 行\n"
        "当前会话已生效，可以直接用 loadSkill 加载它。%s\n\n"
        "如果需要 references/、scripts/ 之类的附件目录，"
        "请继续调用 createDirectory 和 createFile 补上。"
        % (
            str(meta.get("name")).strip(),
            target_dir,
            target_file,
            body_lines,
            note,
        )
    ), skill

