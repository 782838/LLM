"""工具层：注册表 + 全部具体工具。"""
from .registry import Registry, Tool

__all__ = ["Registry", "Tool", "default_registry"]


def default_registry(skills=None, skills_root=None, mcp_manager=None):
    """装上全部工具，返回一个注册表。

    skills       启动时发现的技能列表，传给 loadSkill / createSkill 用
    mcp_manager  MCP 管理器，已连接的话把它的工具一起注册进来
    """
    from . import (
        cli_tools,
        context_tools,
        datetime_tools,
        file_tools,
        office_tools,
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
        office_tools,
    )
    for group in groups:
        for tool in group.build_tools():
            reg.register(tool)

    # loadSkill / createSkill 需要注入技能列表，单独处理
    for tool in skill_tools.build_tools(skills=skills, root=skills_root):
        reg.register(tool)

    # recallContext 需要知道去哪找归档
    for tool in context_tools.build_tools(root=skills_root):
        reg.register(tool)

    # MCP 工具最后注册，撞名时会被跳过而不覆盖本地工具
    if mcp_manager is not None:
        mcp_manager.register_into(reg)

    return reg
