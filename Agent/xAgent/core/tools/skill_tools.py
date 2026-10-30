"""loadSkill 工具：按需加载技能的完整说明或附件文件。

技能清单在启动时已经注入了 System Prompt（只有 name 和 description），
正文不在上下文里。模型需要时调这个工具把正文拉进来。

读取范围严格限制在该技能目录内部。
"""
from .. import skills as skill_store
from .registry import Tool


def build_tools(skills=None, root=None):
    """构造 loadSkill 工具。

    skills 是启动时发现的技能列表，直接闭包进去，
    这样运行期不用反复扫目录。
    """
    def load(name=None, filename=None):
        return skill_store.load_skill(
            name=name, filename=filename, skills=skills, root=root
        )

    return [
        Tool(
            name="loadSkill",
            description=(
                "加载某个技能的完整说明或它引用的附件文件。"
                "只传 name 时返回该技能 SKILL.md 的全文；"
                "同时传 filename 时读取该附件文件，不会重复返回 SKILL.md。"
                "需要按某个技能的规定办事时，先调用它把说明读进来。"
            ),
            func=load,
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "必需的技能名称，取自 System Prompt 里列出的名字。",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "可选。要加载的附件文件，支持相对技能目录的路径、"
                            "项目相对路径或绝对路径。只给文件名时会递归搜索，"
                            "同名文件多于一个时会返回候选列表让你决定。"
                        ),
                    },
                },
            },
            required=["name"],
        ),
    ]
