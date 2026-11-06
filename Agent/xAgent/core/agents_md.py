"""AGENTS.md 支持：一次注入，全程复用。

策略
----
会话开始时，如果项目根有 AGENTS.md，就把它作为**一条历史消息**追加进去：

    history = [
        {"role": "user", "content": "[项目说明 AGENTS.md]\\n\\n<文件内容>"},
        {"role": "assistant", "content": "已了解项目说明，可以开始。"},
        ...后续对话
    ]

为什么只注入一次
--------------
prompt cache 按前缀匹配。如果每轮都重新注入 AGENTS.md，
前缀就变了，缓存全部失效，token 成本会翻倍。

所以：
    - 新会话开始时注入一次
    - 之后不再动它
    - /resume 恢复会话时，如果历史里已经有那条注入消息，就跳过

为什么不放 System Prompt
----------------------
System Prompt 每轮都要发，放那儿等于每轮都花一份 token。
而放进 history 也是一样每轮都发……但区别在于：

任务明确要求「追加到聊天历史」，而且这样 /compact 压缩时
能把项目说明一起压进摘要，比一直占着 System Prompt 更灵活。
"""
import os

AGENTS_FILE = "AGENTS.md"
# 注入消息的固定前缀，用来识别「这条是不是注入的」
MARKER = "[项目说明 AGENTS.md]"
ASSISTANT_ACK = "已了解项目说明，可以开始。"

# 文件读取上限，防止超大文件把上下文撑爆
MAX_CHARS = 30000


class AgentsMdInfo:
    """一份 AGENTS.md 的读取结果。"""

    def __init__(self, found=False, path=None, content="", truncated=False,
                 error=None):
        self.found = found
        self.path = path
        self.content = content
        self.truncated = truncated
        self.error = error

    def __repr__(self):
        return "AgentsMdInfo(found=%s, %d 字符)" % (self.found, len(self.content))


def find(root=None):
    """在项目根找 AGENTS.md，返回路径或 None。"""
    base = root or os.getcwd()
    path = os.path.join(base, AGENTS_FILE)
    return path if os.path.isfile(path) else None


def read(root=None, max_chars=MAX_CHARS):
    """读取 AGENTS.md。"""
    path = find(root)
    if path is None:
        return AgentsMdInfo()

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return AgentsMdInfo(found=True, path=path, error="文件不是 UTF-8 编码")
    except OSError as e:
        return AgentsMdInfo(found=True, path=path, error="读取失败：%s" % e)

    text = text.strip()
    if not text:
        return AgentsMdInfo(found=True, path=path, error="文件是空的")

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
        truncated = True

    return AgentsMdInfo(found=True, path=path, content=text, truncated=truncated)


def already_injected(messages):
    """检查历史里是否已经有 AGENTS.md 注入消息。"""
    for msg in messages or []:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "")
        if content.startswith(MARKER):
            return True
    return False


def build_messages(info):
    """把 AGENTS.md 内容转成两条消息（user + assistant 确认）。

    任务要求「作为一条消息追加」，但 OpenAI 格式里 user 后面跟一条
    assistant 确认更自然，也避免两条连续 user 消息。
    """
    if not info or not info.found or not info.content:
        return []

    body = "%s\n\n%s" % (MARKER, info.content)
    if info.truncated:
        body += "\n\n（文件较长，已截断到 %d 字符。）" % MAX_CHARS

    return [
        {"role": "user", "content": body},
        {"role": "assistant", "content": ASSISTANT_ACK},
    ]


def inject(history, root=None, max_chars=MAX_CHARS):
    """把 AGENTS.md 注入到 history 开头（原地修改）。

    返回 (是否注入, 说明)。已经注入过的不会重复注入。
    """
    if already_injected(history):
        return False, "历史里已经有项目说明，跳过"

    info = read(root, max_chars)
    if not info.found:
        return False, "没有 AGENTS.md"
    if info.error:
        return False, info.error

    messages = build_messages(info)
    if not messages:
        return False, "AGENTS.md 没有可用内容"

    history[0:0] = messages
    note = "已注入 AGENTS.md（%d 字符）" % len(info.content)
    if info.truncated:
        note += "，已截断"
    return True, note
