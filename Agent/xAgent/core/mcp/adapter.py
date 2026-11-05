"""把 MCP 工具适配成 xAgent 的 Tool。

两件事：
    1. 工具名加服务器前缀，避免和本地工具撞名
    2. MCP 的 CallToolResult 有四种内容形态，统一转成给模型看的文本
"""
import json

from ..tools.registry import Tool

# 名字里放这个分隔符，模型看到就能判断哪个 Server 的
NAME_SEP = "__"


def exposed_name(server_name, tool_name):
    """生成暴露给模型的名字：服务器名__工具名。"""
    return "%s%s%s" % (server_name, NAME_SEP, tool_name)


def split_name(name):
    """从暴露名反查 (服务器名, 原始工具名)。没有分隔符返回 (None, name)。"""
    if NAME_SEP in name:
        server, _, tool = name.partition(NAME_SEP)
        return server, tool
    return None, name


def sanitize_schema(schema):
    """规整 MCP 的 inputSchema。

    MCP 给的 schema 已经是 JSON Schema，但有两种情况要处理：
      - 是 None → 给个空对象 schema
      - 顶层类型不是 object → 包一层，因为 Function Call 的参数必须是对象
    """
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}

    if schema.get("type") == "object":
        result = dict(schema)
        result.setdefault("properties", {})
        return result

    # 不是 object 就包一层，避免模型没法传参
    return {
        "type": "object",
        "properties": {"value": schema},
        "required": [],
    }


def normalize_result(result):
    """把 CallToolResult 转成 (文本, 错误信息)。

    content 可能是 TextContent / ImageContent / AudioContent / EmbeddedResource，
    还可能有 structuredContent。全部拼成文本。
    """
    parts = []

    content = getattr(result, "content", None) or []
    for item in content:
        kind = getattr(item, "type", None)

        if kind == "text":
            text = getattr(item, "text", "") or ""
            if text.strip():
                parts.append(text)

        elif kind == "image":
            mime = getattr(item, "mime_type", "image/unknown")
            data = getattr(item, "data", "") or ""
            parts.append("[图片 %s，base64 长度 %d]" % (mime, len(data)))

        elif kind == "audio":
            mime = getattr(item, "mime_type", "audio/unknown")
            data = getattr(item, "data", "") or ""
            parts.append("[音频 %s，base64 长度 %d]" % (mime, len(data)))

        elif kind == "resource":
            res = getattr(item, "resource", None)
            if res is not None:
                uri = getattr(res, "uri", "")
                text = getattr(res, "text", None)
                if text is not None:
                    parts.append("[资源 %s]\n%s" % (uri, text))
                else:
                    blob = getattr(res, "blob", None)
                    parts.append("[资源 %s，二进制 %d 字节]" % (
                        uri, len(blob) if blob else 0))
            else:
                parts.append("[未知资源]")

        else:
            # 兜底：把能读到的字段打印出来
            parts.append(str(item))

    structured = getattr(result, "structured_content", None)
    if structured:
        try:
            parts.append("[结构化数据]\n" + json.dumps(
                structured, ensure_ascii=False, indent=2))
        except (TypeError, ValueError):
            parts.append("[结构化数据]\n" + str(structured))

    text = "\n".join(parts).strip()

    is_error = bool(getattr(result, "is_error", False))
    if is_error:
        return None, text or "MCP 工具返回了错误，但没有给出错误内容。"

    if not text:
        return "（工具执行成功，返回内容为空）", None

    return text, None


def make_tool(server_name, tool_def, session):
    """把一个 MCP 工具定义包装成 xAgent 的 Tool。"""
    original = tool_def.name
    name = exposed_name(server_name, original)

    description = (getattr(tool_def, "description", None) or "").strip()
    if not description:
        description = "MCP 工具 %s（来自 %s）" % (original, server_name)
    else:
        description = "[MCP:%s] %s" % (server_name, description)

    schema = sanitize_schema(getattr(tool_def, "input_schema", None))
    required = schema.get("required") or []
    if not isinstance(required, list):
        required = []

    def call(**kwargs):
        """真正执行时转发到 MCP Server。"""
        try:
            result = session.call_tool(original, kwargs)
        except TimeoutError as e:
            return None, "MCP 调用超时：%s（工具 %s）" % (e, name)
        except Exception as e:
            return None, "MCP 调用失败：%s: %s（工具 %s）" % (
                type(e).__name__, e, name)

        text, error = normalize_result(result)
        if error:
            return None, error
        return text, None

    return Tool(
        name=name,
        description=description,
        func=call,
        parameters=schema,
        required=required,
    )
