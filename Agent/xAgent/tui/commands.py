"""斜杠命令定义。

放这里的好处：命令清单、别名、说明集中一处，
补全面板和帮助信息都从这儿读，不会两处不一致。
"""


class Command:
    """一个斜杠命令。"""

    def __init__(self, name, aliases, description, handler, needs_idle=True):
        self.name = name              # 不带斜杠，比如 "new"
        self.aliases = list(aliases or [])
        self.description = description
        self.handler = handler        # 界面里的 action 方法名
        self.needs_idle = needs_idle  # 是否要求当前没在跑任务

    @property
    def text(self):
        return "/" + self.name

    def matches(self, typed):
        """typed 是否匹配本命令（含别名）。用来做补全过滤。"""
        typed = typed.lstrip("/").lower()
        if not typed:
            return True
        if self.name.startswith(typed):
            return True
        return any(a.startswith(typed) for a in self.aliases)

    def __repr__(self):
        return "Command(/%s)" % self.name


# 命令清单。handler 是 tui/app.py 里的方法名。
COMMANDS = [
    Command("new", ["n"], "新建会话（会先保存当前会话）", "do_new"),
    Command("resume", ["r", "sessions"], "从历史会话里选一个恢复", "do_resume"),
    Command("save", ["s"], "保存当前会话", "do_save"),
    Command("compact", ["c"], "压缩上下文，把历史压成摘要", "do_compact"),
    Command("model", ["m"], "切换模型", "do_model", needs_idle=True),
    Command("tools", ["t"], "列出可用工具", "do_tools", needs_idle=False),
    Command("skills", ["sk"], "列出已加载的技能", "do_skills", needs_idle=False),
    Command("mcp", [], "查看 MCP 服务器连接状态", "do_mcp", needs_idle=False),
    Command("context", ["ctx"], "查看上下文用量详情", "do_context", needs_idle=False),
    Command("clear", ["cls"], "清屏并清空历史（会先确认）", "do_clear", needs_idle=False),
    Command("help", ["?", "h"], "显示这条帮助", "do_help", needs_idle=False),
    Command("quit", ["exit", "q"], "退出程序", "do_quit", needs_idle=False),
]

_BY_NAME = {}
for _cmd in COMMANDS:
    _BY_NAME[_cmd.name] = _cmd
    for _a in _cmd.aliases:
        _BY_NAME.setdefault(_a, _cmd)


def resolve(text):
    """把 `/new` 或 `/n` 解析成 Command，找不到返回 None。"""
    if not text:
        return None
    key = text.strip().lstrip("/").split()[0].lower() if text.strip().lstrip("/") else ""
    return _BY_NAME.get(key)


def suggest(typed):
    """按已输入内容给出候选，用于补全面板。"""
    typed = (typed or "").lstrip("/").lower()
    if not typed:
        return list(COMMANDS)
    return [c for c in COMMANDS if c.matches(typed)]


def help_text():
    """帮助信息。"""
    lines = ["可用命令：", ""]
    width = max(len(c.text) for c in COMMANDS) + 2
    for c in COMMANDS:
        alias = ""
        if c.aliases:
            alias = "  （" + "、".join("/" + a for a in c.aliases) + "）"
        lines.append("  %s%s%s" % (c.text.ljust(width), c.description, alias))
    lines.append("")
    lines.append("快捷键：Ctrl+M 换模型　Ctrl+N 新会话　Ctrl+L 清屏　F1 工具　F2 技能")
    lines.append("输入 / 会弹出补全面板，上下键选择，回车确认。")
    return "\n".join(lines)
