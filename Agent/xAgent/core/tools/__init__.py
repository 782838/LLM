"""工具层：注册表 + 12 个具体工具。"""
from .registry import Registry, Tool

__all__ = ["Registry", "Tool", "default_registry"]


def default_registry():
    """装上全部 12 个工具，返回一个注册表。"""
    from . import datetime_tools, file_tools

    reg = Registry()
    for tool in datetime_tools.build_tools():
        reg.register(tool)
    for tool in file_tools.build_tools():
        reg.register(tool)
    return reg
