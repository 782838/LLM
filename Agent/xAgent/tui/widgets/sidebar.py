"""左侧边栏：显示模型、工具、技能和会话信息。"""
from rich.text import Text
from textual.containers import VerticalScroll


class Sidebar(VerticalScroll):
    """上下文信息面板。数据先缓存，render 时再拼。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = ""
        self._tools = []
        self._skills = []
        self._skill_notes = []
        self._turns = 0

    def setup(self, model, tools, skills, skill_notes=None):
        self._model = model or "（未配置）"
        self._tools = list(tools)
        self._skills = list(skills)
        self._skill_notes = list(skill_notes or [])
        self._turns = 0
        self.refresh()

    def bump_turn(self):
        self._turns += 1
        self.refresh()

    # ---- 渲染 ----
    def _section(self, title, items, style="white", limit=None):
        lines = [Text(title, style="bold #94a3b8")]
        shown = items if limit is None else items[:limit]
        for item in shown:
            t = Text("  ")
            t.append("· ", style="#475569")
            t.append(str(item), style=style)
            lines.append(t)
        if limit is not None and len(items) > limit:
            more = Text("  ")
            more.append("… %d 个" % (len(items) - limit), style="dim #64748b")
            lines.append(more)
        return lines

    def render(self):
        if not self._model:
            return Text("准备中…", style="dim #64748b")

        blocks = []

        blocks.append(Text("模型", style="bold #94a3b8"))
        model_line = Text("  ")
        model_line.append(self._model, style="#7dd3fc")
        blocks.append(model_line)
        blocks.append(Text(""))

        blocks.extend(self._section(
            "工具 %d" % len(self._tools), self._tools, style="#a5b4fc", limit=6))
        blocks.append(Text(""))

        names = [s.name for s in self._skills]
        blocks.extend(self._section(
            "技能 %d" % len(names), names, style="#86efac", limit=6))
        for note in self._skill_notes[:3]:
            t = Text("  ")
            t.append("! " + str(note)[:26], style="dim #fbbf24")
            blocks.append(t)
        blocks.append(Text(""))

        blocks.append(Text("会话", style="bold #94a3b8"))
        turn_line = Text("  ")
        turn_line.append("%d 轮对话" % self._turns, style="#cbd5e1")
        blocks.append(turn_line)

        return Text("\n").join(blocks)
