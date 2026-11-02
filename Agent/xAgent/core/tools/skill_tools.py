"""技能工具：loadSkill 按需加载，createSkill 让模型自己建技能。

技能清单在启动时已经注入了 System Prompt（只有 name 和 description），
正文不在上下文里。模型需要时调 loadSkill 把正文拉进来。
新技能用 createSkill 创建，创建后当前会话立即可用。
"""
from .. import skills as skill_store
from .registry import Tool


def build_tools(skills=None, root=None):
    """构造技能相关工具。

    skills 是启动时发现的技能列表，直接闭包进去 ——
    createSkill 往里追加，loadSkill 从里面查，两边看到的是同一份数据。
    """
    def load(name=None, filename=None):
        return skill_store.load_skill(
            name=name, filename=filename, skills=skills, root=root
        )

    def create(name=None, skillContext=None):
        text, _skill = skill_store.create_skill(
            name=name, skill_context=skillContext, root=root, skills=skills
        )
        return text

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
        Tool(
            name="createSkill",
            description=(
                "创建一个新的技能。会在 <项目根>/.agents/skills/<name>/ 下生成 SKILL.md。"
                "name 只能用小写字母、数字和连字符，例如 my-skill。"
                "skillContext 必须是 SKILL.md 的完整内容，包含 YAML Frontmatter"
                "（至少有 name 和 description 两个字段）和正文规则。"
                "已有同名技能时不会覆盖，会返回提示。"
                "如果需要 references/、scripts/ 等附件目录，"
                "创建完技能后继续调用 createDirectory 和 createFile 补充。"
            ),
            func=create,
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "技能名称，只能用小写字母、数字和连字符，"
                            "必须以字母或数字开头，例如 my-skill、report-gen。"
                            "它同时是技能目录名。"
                        ),
                    },
                    "skillContext": {
                        "type": "string",
                        "description": (
                            "SKILL.md 的完整内容。必须以 --- 开头写 YAML Frontmatter，"
                            "头部包含 name 和 description，然后写正文规则。"
                            "格式示例：\n"
                            "---\n"
                            "name: 示例技能\n"
                            "description: 一句话说明这个技能做什么\n"
                            "---\n"
                            "1. 具体规则一\n"
                            "2. 具体规则二"
                        ),
                    },
                },
            },
            required=["name", "skillContext"],
        ),
    ]
