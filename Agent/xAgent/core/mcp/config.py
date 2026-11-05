"""读 .mcp.json 配置。

位置规则跟技能目录一致：以**程序启动时的用户工作目录**为项目根，
不是源码所在目录。
"""
import json
import os

CONFIG_NAME = ".mcp.json"

# 支持两种写法：任务的 type 用下划线，官方 SDK 生态常用连字符
STDIO_TYPES = {"stdio"}
HTTP_TYPES = {"streamable_http", "streamable-http", "http", "sse"}


class McpConfigError(Exception):
    """配置文件不合法。"""


class ServerConfig:
    """一个 MCP Server 的连接配置。"""

    def __init__(self, name, type_, url=None, command=None, args=None,
                 env=None, cwd=None, headers=None):
        self.name = name
        self.type = type_
        self.url = url
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.headers = dict(headers or {})
        self.session = None
        self.tools = []
        self.error = None

    @property
    def is_http(self):
        return self.type in HTTP_TYPES

    @property
    def is_stdio(self):
        return self.type in STDIO_TYPES

    def __repr__(self):
        target = self.url if self.is_http else ("%s %s" % (self.command, " ".join(self.args)))
        return "ServerConfig(%r, %s, %s)" % (self.name, self.type, target)


def config_path(root=None):
    """返回 .mcp.json 的绝对路径。"""
    return os.path.join(root or os.getcwd(), CONFIG_NAME)


def find_config(root=None):
    """找 .mcp.json，找不到返回 None。"""
    path = config_path(root)
    return path if os.path.isfile(path) else None


def parse_server(name, raw):
    """解析单个 Server 配置。返回 (ServerConfig, 错误信息)。"""
    if not isinstance(raw, dict):
        return None, "%s 的配置不是对象。" % name

    type_ = str(raw.get("type") or "").strip().lower()

    # 没写 type 时按有无 url 猜
    if not type_:
        if raw.get("url"):
            type_ = "streamable_http"
        elif raw.get("command"):
            type_ = "stdio"
        else:
            return None, "%s 既没有 url 也没有 command，无法判断连接方式。" % name

    if type_ in HTTP_TYPES:
        url = str(raw.get("url") or "").strip()
        if not url:
            return None, "%s 是 HTTP 类型但缺少 url。" % name
        if not url.lower().startswith(("http://", "https://")):
            return None, "%s 的 url 必须以 http:// 或 https:// 开头，收到：%s" % (name, url)
        return ServerConfig(
            name=name,
            type_="streamable_http",
            url=url,
            headers=raw.get("headers") or {},
        ), None

    if type_ in STDIO_TYPES:
        command = str(raw.get("command") or "").strip()
        if not command:
            return None, "%s 是 stdio 类型但缺少 command。" % name
        args = raw.get("args") or []
        if not isinstance(args, list):
            return None, "%s 的 args 必须是数组。" % name
        return ServerConfig(
            name=name,
            type_="stdio",
            command=command,
            args=[str(a) for a in args],
            env=raw.get("env") or {},
            cwd=raw.get("cwd"),
        ), None

    return None, (
        "%s 的 type「%s」不支持。可用：streamable_http（或 streamable-http）、stdio。"
        % (name, raw.get("type"))
    )


def load(root=None):
    """读 .mcp.json，返回 (ServerConfig 列表, 提示信息列表)。

    文件不存在不算错误 —— 没有配置就是没有 MCP 工具，正常启动。
    """
    notes = []
    path = find_config(root)

    if path is None:
        return [], notes

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise McpConfigError("%s 不是合法 JSON：%s" % (path, e))
    except OSError as e:
        raise McpConfigError("读取 %s 失败：%s" % (path, e))

    if not isinstance(data, dict):
        raise McpConfigError("%s 顶层必须是一个对象。" % path)

    servers_raw = data.get("mcpServers")
    if servers_raw is None:
        servers_raw = data.get("mcp_servers")
    if not isinstance(servers_raw, dict):
        raise McpConfigError(
            "%s 里缺少 mcpServers 字段，或者它不是对象。"
            "正确格式：{\"mcpServers\": {\"名字\": {\"type\": \"streamable_http\", \"url\": \"...\"}}}"
            % path
        )

    servers = []
    for name, raw in servers_raw.items():
        name = str(name).strip()
        if not name:
            notes.append("跳过了一个没有名字的 Server 配置。")
            continue
        cfg, err = parse_server(name, raw)
        if err:
            notes.append(err)
            continue
        servers.append(cfg)

    return servers, notes
