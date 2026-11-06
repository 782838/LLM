"""上下文检索工具：recallContext。

压缩后摘要可能丢了细节，模型可以调这个工具去原始归档里翻。
纯本地关键词匹配，不依赖向量库。
"""
from .. import context as ctx
from .registry import Tool


def build_tools(root=None):
    """构造 recallContext 工具。

    root 是项目根，决定去哪个 .agents/context/ 找归档。
    """
    def recall(id=None, text=None):
        result, err = ctx.recall(text=text, archive_id=id, root=root)
        if err:
            return err
        return result

    return [
        Tool(
            name="recallContext",
            description=(
                "检索历史上下文归档。上下文被 /compact 压缩过之后，"
                "如果摘要里缺少某些细节，用这个工具去原始记录里查。\n"
                "text 是必需的关键词；id 可选，指定只查某个归档，不传则搜索所有归档。\n"
                "返回匹配的原文片段、归档编号和消息位置。"
            ),
            func=recall,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要查找的关键词或文本片段，例如某个文件路径、函数名、报错信息。",
                    },
                    "id": {
                        "type": "string",
                        "description": (
                            "可选。归档编号，形如 20261022-153000。"
                            "不传则在所有历史归档里搜索。"
                        ),
                    },
                },
            },
            required=["text"],
        ),
    ]
