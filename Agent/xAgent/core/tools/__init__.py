"""工具层：注册表 + 全部具体工具。"""
from .registry import Registry, Tool

__all__ = ["Registry", "Tool", "default_registry"]


def default_registry(skills=None, skills_root=None):
    """装上全部工具，返回一个注册表。

    skills 是启动时发现的技能列表，传给 loadSkill 用。
    """
    from . import (
        cli_tools,
        datetime_tools,
        file_tools,
        search_tools,
        skill_tools,
        web_tools,
    )

    reg = Registry()
    groups = (
        datetime_tools,
        file_tools,
        web_tools,
        search_tools,
        cli_tools,
    )
    for group in groups:
        for tool in group.build_tools():
            reg.register(tool)

    # loadSkill 需要注入技能列表，单独处理
    for tool in skill_tools.build_tools(skills=skills, root=skills_root):
        reg.register(tool)

    return reg
