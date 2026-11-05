"""左侧边栏：模型（可点击）、工具、技能、会话信息。"""
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from .model_box import ModelBox


class InfoPanel(Static):
    """模型以下的那些信息。数据由 Sidebar 推过来。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tools = []
        self.skills = []
        self.skill_notes = []
        self.turns = 0

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
        blocks = [Text("")]

        blocks.extend(self._section(
            "工具 %d" % len(self.tools), self.tools, style="#a5b4fc", limit=6))
        blocks.append(Text(""))

        names = [s.name for s in self.skills]
        blocks.extend(self._section(
            "技能 %d" % len(names), names, style="#86efac", limit=6))
        for note in self.skill_notes[:3]:
            t = Text("  ")
            t.append("! " + str(note)[:24], style="dim #fbbf24")
            blocks.append(t)
        blocks.append(Text(""))

        blocks.append(Text("会话", style="bold #94a3b8"))
        turn_line = Text("  ")
        turn_line.append("%d 轮对话" % self.turns, style="#cbd5e1")
        blocks.append(turn_line)

        return Text("\n").join(blocks)

    def update_data(self, tools, skills, skill_notes, turns):
        self.tools = list(tools)
        self.skills = list(skills)
        self.skill_notes = list(skill_notes or [])
        self.turns = turns
        self.refresh()


class Sidebar(VerticalScroll):
    """上下文信息面板。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = ""
        self._tools = []
        self._skills = []
        self._skill_notes = []
        self._turns = 0

    def compose(self):
        yield ModelBox(id="model-box")
        yield InfoPanel(id="info-panel")

    def setup(self, model, tools, skills, skill_notes=None):
        self._model = model or "（未配置）"
        self._tools = list(tools)
        self._skills = list(skills)
        self._skill_notes = list(skill_notes or [])
        self._turns = 0
        self._push()

    def bump_turn(self):
        self._turns += 1
        self._push()

    def _push(self):
        self.query_one("#model-box", ModelBox).set_model(self._model)
        self.query_one("#info-panel", InfoPanel).update_data(
            self._tools, self._skills, self._skill_notes, self._turns
        )
