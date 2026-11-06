"""统一配置中心。

设计目标
--------
把散落在各模块里的硬编码常量集中到一处，来源按优先级：
    1. config.ini 里的对应小节
    2. 这里定义的默认值

用法
----
    from core.settings import settings

    settings.cli_timeout        # 从 [tools] cli_timeout 读，没配就用 30
    settings.get("tools", "cli_timeout", 30)   # 显式写法

为什么不用「一次性加载成 dict」
--------------------------
各模块在 import 时就会读常量（比如 `DEFAULT_TIMEOUT = 30`），
如果配置晚于 import 才加载，模块就拿不到新值。
所以这里用「延迟读取 + 缓存」：第一次访问某键时才去查配置，
并缓存结果。`reload()` 可以清缓存，配合界面改配置用。
"""
import os
import re

# ---------------------------------------------------------------- 默认值表
#
# 结构：{ 小节: { 键: 默认值 } }
# 顶层小节用 "" 表示（就是 config.ini 里没有 [] 包裹的那部分）
DEFAULTS = {
    "": {
        "base_url": "http://127.0.0.1:11437/v1",
        "model": "",
        "api_key": "",
        "timeout": 300,
        "context_window": None,      # None 表示用 context 里的默认 128k
    },
    "agent": {
        "max_tool_rounds": 12,
        "session_dir": ".agents/sessions",
        "auto_save_on_new": True,    # /new 时自动保存当前会话
        "ask_save_on_exit": True,    # 退出时询问是否保存（false 则按 auto_save_on_exit 静默处理）
        "auto_save_on_exit": False,  # 不询问时，退出要不要直接保存
    },
    "context": {
        "warn_ratio": 0.6,
        "target_summary_tokens": 5000,
        "chars_per_token": 1.4,
        "max_recall_chars": 6000,
        "max_snippet_chars": 400,
        "archive_dir": ".agents/context",
    },
    "skills": {
        "max_file_chars": 30000,
        "max_name_len": 64,
        "dir": ".agents/skills",
    },
    "tools": {
        "cli_timeout": 30,
        "cli_max_timeout": 120,
        "cli_max_output": 4000,
        "office_timeout": 60,
        "office_max_timeout": 300,
        "office_max_output": 4000,
        "fetch_max_chars": 20000,
        "fetch_timeout": 30,
        "web_search_timeout": 30,
        "search_top_k": 10,
        "search_max_top_k": 50,
        "search_snippet_chars": 300,
        "read_max_bytes": 204800,
    },
    "mcp": {
        "connect_timeout": 30,
        "list_timeout": 30,
        "call_timeout": 120,
        "config_name": ".mcp.json",
        "enabled": True,
    },
    "ui": {
        "sidebar_width": 28,
        "message_limit": 500,
    },
    "project": {
        "max_up_levels": 4,
        "state_file": ".last-project-root",
    },
}

# 需要转成 bool 的键（ini 里只有字符串）
_BOOL_KEYS = {
    ("agent", "auto_save_on_new"),
    ("agent", "ask_save_on_exit"),
    ("agent", "auto_save_on_exit"),
    ("mcp", "enabled"),
}

# 需要转成 int 的键
_INT_KEYS = {
    ("", "timeout"),
    ("", "context_window"),
    ("agent", "max_tool_rounds"),
    ("context", "target_summary_tokens"),
    ("context", "max_recall_chars"),
    ("context", "max_snippet_chars"),
    ("skills", "max_file_chars"),
    ("skills", "max_name_len"),
    ("tools", "cli_timeout"),
    ("tools", "cli_max_timeout"),
    ("tools", "cli_max_output"),
    ("tools", "office_timeout"),
    ("tools", "office_max_timeout"),
    ("tools", "office_max_output"),
    ("tools", "fetch_max_chars"),
    ("tools", "fetch_timeout"),
    ("tools", "web_search_timeout"),
    ("tools", "search_top_k"),
    ("tools", "search_max_top_k"),
    ("tools", "search_snippet_chars"),
    ("tools", "read_max_bytes"),
    ("mcp", "connect_timeout"),
    ("mcp", "list_timeout"),
    ("mcp", "call_timeout"),
    ("ui", "sidebar_width"),
    ("ui", "message_limit"),
    ("project", "max_up_levels"),
}

# 需要转成 float 的键
_FLOAT_KEYS = {
    ("context", "warn_ratio"),
    ("context", "chars_per_token"),
}


class Settings:
    """配置读取器，带缓存。"""

    def __init__(self):
        self._sections = None       # 原始 ini 解析结果（全小写键）
        self._cache = {}
        self._source = None         # 配置文件路径，方便报错和显示

    # ---- 加载 ----
    def load(self, path=None):
        """读配置文件。path 为 None 时自动找。"""
        from .config import find_config, parse_ini

        self._cache.clear()
        target = path or find_config()

        if target is None:
            self._sections = {}
            self._source = None
            return self

        try:
            self._sections = parse_ini(target)
            self._source = target
        except Exception:
            # 配置文件坏了也要能启动，用全默认值
            self._sections = {}
            self._source = None
        return self

    def reload(self):
        """清缓存并重新读。界面改完配置后调。"""
        return self.load(self._source)

    @property
    def source(self):
        return self._source

    # ---- 取值 ----
    def get(self, section, key, default=None):
        """读一个配置项。

        section 用 "" 表示顶层。找不到就用 DEFAULTS 里的默认值，
        再找不到就用传入的 default。
        """
        section = (section or "").lower()
        key = (key or "").lower()
        cache_key = (section, key)

        if cache_key in self._cache:
            return self._cache[cache_key]

        if self._sections is None:
            self.load()

        raw = None
        if self._sections:
            raw = self._sections.get(section, {}).get(key)

        if raw is None or raw == "":
            # 没有配置项，用默认值表
            value = DEFAULTS.get(section, {}).get(key, default)
        else:
            value = self._coerce(section, key, raw)

        self._cache[cache_key] = value
        return value

    def _coerce(self, section, key, raw):
        """把 ini 里的字符串转成合适的类型。"""
        text = str(raw).strip()
        pair = (section, key)

        if pair in _BOOL_KEYS:
            return text.lower() in ("1", "true", "yes", "on", "y")

        if pair in _INT_KEYS:
            try:
                return int(text)
            except ValueError:
                return DEFAULTS.get(section, {}).get(key)

        if pair in _FLOAT_KEYS:
            try:
                return float(text)
            except ValueError:
                return DEFAULTS.get(section, {}).get(key)

        return text

    # ---- 便捷属性：常用项直接读 ----
    @property
    def max_tool_rounds(self):
        return self.get("agent", "max_tool_rounds")

    @property
    def session_dir(self):
        return self.get("agent", "session_dir")

    @property
    def auto_save_on_new(self):
        return self.get("agent", "auto_save_on_new")

    @property
    def ask_save_on_exit(self):
        return self.get("agent", "ask_save_on_exit")

    @property
    def auto_save_on_exit(self):
        return self.get("agent", "auto_save_on_exit")

    @property
    def warn_ratio(self):
        return self.get("context", "warn_ratio")

    @property
    def target_summary_tokens(self):
        return self.get("context", "target_summary_tokens")

    @property
    def chars_per_token(self):
        return self.get("context", "chars_per_token")

    @property
    def max_recall_chars(self):
        return self.get("context", "max_recall_chars")

    @property
    def max_snippet_chars(self):
        return self.get("context", "max_snippet_chars")

    @property
    def archive_dir(self):
        return self.get("context", "archive_dir")

    @property
    def max_file_chars(self):
        return self.get("skills", "max_file_chars")

    @property
    def max_name_len(self):
        return self.get("skills", "max_name_len")

    @property
    def skills_dirname(self):
        return self.get("skills", "dir")

    @property
    def cli_timeout(self):
        return self.get("tools", "cli_timeout")

    @property
    def cli_max_timeout(self):
        return self.get("tools", "cli_max_timeout")

    @property
    def cli_max_output(self):
        return self.get("tools", "cli_max_output")

    @property
    def office_timeout(self):
        return self.get("tools", "office_timeout")

    @property
    def office_max_timeout(self):
        return self.get("tools", "office_max_timeout")

    @property
    def office_max_output(self):
        return self.get("tools", "office_max_output")

    @property
    def fetch_max_chars(self):
        return self.get("tools", "fetch_max_chars")

    @property
    def fetch_timeout(self):
        return self.get("tools", "fetch_timeout")

    @property
    def search_timeout(self):
        return self.get("tools", "web_search_timeout")

    @property
    def search_top_k(self):
        return self.get("tools", "search_top_k")

    @property
    def search_max_top_k(self):
        return self.get("tools", "search_max_top_k")

    @property
    def search_snippet_chars(self):
        return self.get("tools", "search_snippet_chars")

    @property
    def read_max_bytes(self):
        return self.get("tools", "read_max_bytes")

    @property
    def mcp_connect_timeout(self):
        return self.get("mcp", "connect_timeout")

    @property
    def mcp_list_timeout(self):
        return self.get("mcp", "list_timeout")

    @property
    def mcp_call_timeout(self):
        return self.get("mcp", "call_timeout")

    @property
    def mcp_enabled(self):
        return self.get("mcp", "enabled")

    @property
    def mcp_config_name(self):
        return self.get("mcp", "config_name")

    @property
    def sidebar_width(self):
        return self.get("ui", "sidebar_width")

    @property
    def max_up_levels(self):
        return self.get("project", "max_up_levels")

    @property
    def state_file(self):
        return self.get("project", "state_file")


# 全局单例
settings = Settings()


# ---------------------------------------------------------------- 配置模板

def template_text():
    """生成完整的 config.ini 模板（含 mock 值）。"""
    lines = [
        "# xAgent 配置文件",
        "# 改完这个文件需要重启程序才生效。",
        "",
        "# ============ 模型接入 ============",
        "# 任何 OpenAI 兼容接口都行：本地 ollama、ModelScope、各家云服务",
        "base_url = http://127.0.0.1:11437/v1",
        "model = your-model-name",
        "api_key = sk-your-key-here",
        "",
        "# 单次请求超时（秒）",
        "timeout = 300",
        "",
        "# 上下文窗口大小（tokens）。留空则默认 128k，界面上会标「默认」",
        "# 常见值：32768、131072、1048576",
        "context_window =",
        "",
        "# ============ Agent 行为 ============",
        "[agent]",
        "# 单轮对话里最多允许几轮工具调用，防止死循环",
        "max_tool_rounds = 12",
        "# 会话保存目录（相对项目根）",
        "session_dir = .agents/sessions",
        "# /new 新建会话时是否自动保存当前会话",
        "auto_save_on_new = true",
        "# 退出时是否弹窗询问「保存这个会话」（推荐 true，避免白聊一场）",
        "ask_save_on_exit = true",
        "# 不弹窗时（ask_save_on_exit = false）退出要不要直接保存",
        "auto_save_on_exit = false",
        "",
        "# ============ 上下文压缩 ============",
        "[context]",
        "# 用量达到窗口的多少比例时提示压缩",
        "warn_ratio = 0.6",
        "# 摘要目标 token 数",
        "target_summary_tokens = 5000",
        "# 字符转 token 的估算系数（拿不到真实 usage 时用）",
        "chars_per_token = 1.4",
        "# recallContext 单次返回的最大字符数",
        "max_recall_chars = 6000",
        "# 归档目录（相对项目根）",
        "archive_dir = .agents/context",
        "",
        "# ============ 技能 ============",
        "[skills]",
        "# 技能目录（相对项目根）",
        "dir = .agents/skills",
        "# 单个技能文件读取上限（字符）",
        "max_file_chars = 30000",
        "",
        "# ============ 工具参数 ============",
        "[tools]",
        "# RunCli 默认超时（秒）与输出上限（字符）",
        "cli_timeout = 30",
        "cli_max_timeout = 120",
        "cli_max_output = 4000",
        "",
        "# officeDoc 超时与输出上限",
        "office_timeout = 60",
        "office_max_timeout = 300",
        "office_max_output = 4000",
        "",
        "# fetchWeb 正文上限与超时",
        "fetch_max_chars = 20000",
        "fetch_timeout = 30",
        "",
        "# searchWeb 参数",
        "web_search_timeout = 30",
        "search_top_k = 10",
        "search_max_top_k = 50",
        "search_snippet_chars = 300",
        "",
        "# readFile 单次读取上限（字节）",
        "read_max_bytes = 204800",
        "",
        "# ============ MCP ============",
        "[mcp]",
        "# 是否启用 MCP（关掉就完全不连）",
        "enabled = true",
        "# 配置文件位置（相对项目根）",
        "config_name = .mcp.json",
        "# 连接 / 列工具 / 调用的超时（秒）",
        "connect_timeout = 30",
        "list_timeout = 30",
        "call_timeout = 120",
        "",
        "# ============ 界面 ============",
        "[ui]",
        "# 侧边栏宽度（列）",
        "sidebar_width = 28",
        "",
        "# ============ 项目定位 ============",
        "[project]",
        "# 找不到配置时最多往上翻几层",
        "max_up_levels = 4",
        "",
        "# ============ 联网搜索密钥 ============",
        "[search]",
        "# 百度千帆 AI 搜索的 API Key，给 searchWeb 工具用",
        "# 获取地址：https://console.bce.baidu.com/qianfan/ais/console/apiKey",
        "baidu_qianfan_api_key =",
        "",
    ]
    return "\n".join(lines)


def create_config(path):
    """在指定路径生成一份配置模板。返回 (成功与否, 路径或错误)。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(template_text())
    except OSError as e:
        return False, "写入失败：%s" % e
    return True, path
