"""上下文管理：token 统计、归档、压缩、检索。

设计原则
--------
简单、能看懂。不用向量库、不用 embedding，归档就是 JSONL，检索就是子串匹配。

几个约定
--------
    归档目录   <项目根>/.agents/context/
    归档文件   <编号>.jsonl，一行一条消息
    编号格式   20261022-153000
    默认窗口   128k（拿不到真实值时用，界面上标「默认」）
    警告阈值   60%
    摘要目标   约 5000 tokens

压缩流程（顺序不能变）
--------------------
    1. 先归档 —— 写盘失败就整个中止
    2. 调 LLM 生成摘要 —— 失败就中止，原上下文不动
    3. 校验摘要 —— 为空或明显异常就中止
    4. 这才替换 history
"""
import json
import os
import re
import time

from .settings import settings

# ---------------------------------------------------------------- 常量（从配置读）

DEFAULT_WINDOW = 128 * 1024       # 拿不到真实窗口时的兜底


def _warn_ratio():
    return settings.warn_ratio


def _target_summary_tokens():
    return settings.target_summary_tokens


def _chars_per_token():
    return settings.chars_per_token or 1.4


def _context_dirname():
    return settings.archive_dir


def _max_recall_chars():
    return settings.max_recall_chars


def _max_snippet_chars():
    return settings.max_snippet_chars


# ---------------------------------------------------------------- Prompt

COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


# ---------------------------------------------------------------- token 估算

def estimate_tokens(text):
    """估算一段文本的 token 数。

    优先用真实 usage（由调用方传进来），这个只在拿不到时兜底。
    """
    if not text:
        return 0
    return max(1, int(len(str(text)) / _chars_per_token()))


def message_tokens(message):
    """估算一条消息的 token 数，含工具调用部分。"""
    if not isinstance(message, dict):
        return estimate_tokens(message)

    total = 0
    content = message.get("content") or ""
    total += estimate_tokens(content)

    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        total += estimate_tokens(fn.get("name"))
        total += estimate_tokens(fn.get("arguments"))

    # 每条消息有固定的角色开销，粗算 4
    total += 4
    return total


def history_tokens(messages):
    """估算一组消息的总 token。"""
    return sum(message_tokens(m) for m in (messages or []))


# ---------------------------------------------------------------- 窗口与阈值

def resolve_window(config=None):
    """返回 (窗口大小, 是否默认值)。

    优先级：config.context_window > 默认 128k
    """
    if config is not None:
        raw = getattr(config, "context_window", None)
        if raw:
            try:
                value = int(raw)
                if value > 0:
                    return value, False
            except (TypeError, ValueError):
                pass
    return DEFAULT_WINDOW, True


class Usage:
    """一次上下文用量的快照。"""

    def __init__(self, used, window, is_default, exact=False):
        self.used = int(used)
        self.window = int(window)
        self.is_default = bool(is_default)
        self.exact = bool(exact)      # True 表示用了 API 返回的真实 usage

    @property
    def ratio(self):
        if self.window <= 0:
            return 0.0
        return min(1.0, self.used / self.window)

    @property
    def percent(self):
        return self.ratio * 100

    @property
    def should_warn(self):
        return self.ratio >= _warn_ratio()

    @property
    def remaining(self):
        return max(0, self.window - self.used)

    def k_text(self, value=None):
        """把 token 数显示成 k。"""
        v = self.used if value is None else value
        return "%.1fk" % (v / 1024.0)

    def summary(self):
        """一行显示文案：12.3k / 128k（默认） 9.6%"""
        tag = "（默认）" if self.is_default else ""
        return "%s / %s%s  %.1f%%" % (
            self.k_text(), self.k_text(self.window), tag, self.percent
        )


def compute_usage(system_prompt, history, window, is_default,
                  real_prompt_tokens=None, last_hist_tokens=0):
    """算当前上下文用量。

    real_prompt_tokens 是上一次请求 API 返回的 prompt_tokens。
    它反映「上次请求那一刻」的上下文，本次可能又追加了消息，
    所以要在它的基础上补上新增部分的估算。

    last_hist_tokens 是上次请求时的历史估算值，由调用方（Agent）记录。
    """
    system_tokens = estimate_tokens(system_prompt)
    hist_tokens = history_tokens(history)

    if real_prompt_tokens:
        # 真实值已包含 system + 当时的历史，这里只补新增的消息
        delta = max(0, hist_tokens - (last_hist_tokens or 0))
        used = int(real_prompt_tokens) + delta
        exact = True
    else:
        used = system_tokens + hist_tokens
        exact = False

    return Usage(used, window, is_default, exact), hist_tokens


# ---------------------------------------------------------------- 归档编号

_NUMBER_RE = re.compile(r"^(\d{8})-(\d{6})$")


def new_archive_id(now=None):
    """生成归档编号：20261022-153000。"""
    t = now or time.localtime()
    return time.strftime("%Y%m%d-%H%M%S", t)


def valid_archive_id(value):
    return bool(_NUMBER_RE.match(str(value or "").strip()))


def context_dir(root=None):
    """归档目录的绝对路径。"""
    base = root or os.getcwd()
    # 配置里的路径可能用正斜杠，统一用系统分隔符
    parts = _context_dirname().replace("\\", "/").split("/")
    return os.path.join(base, *[p for p in parts if p])


# ---------------------------------------------------------------- 归档

def _message_for_archive(message):
    """把一条消息整理成归档用的字典，字段一个不丢。"""
    if not isinstance(message, dict):
        return {"role": "unknown", "content": str(message)}

    item = {
        "role": message.get("role") or "",
        "content": message.get("content"),
    }
    if message.get("tool_calls"):
        item["tool_calls"] = message["tool_calls"]
    if message.get("tool_call_id"):
        item["tool_call_id"] = message["tool_call_id"]
    if message.get("name"):
        item["name"] = message["name"]
    return item


def archive(root, history, archive_id=None, now=None):
    """把 current history 完整写进 JSONL。

    返回 (归档编号, 文件路径, 错误信息)。成功时错误信息为 None。
    写盘失败必须让调用方中止压缩 —— 原始记录丢了就没法检索了。
    """
    if not history:
        return None, None, "没有可归档的消息"

    aid = archive_id or new_archive_id(now)
    folder = context_dir(root)

    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return None, None, "创建归档目录失败：%s" % e

    path = os.path.join(folder, aid + ".jsonl")

    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for seq, message in enumerate(history, 1):
                item = _message_for_archive(message)
                item["seq"] = seq
                item["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as e:
        # 写了一半算失败，删掉残文件
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        return None, None, "写归档文件失败：%s" % e

    return aid, path, None


def list_archives(root=None):
    """列出所有归档，新的在前。返回 [(编号, 路径, 大小, 消息数)]。"""
    folder = context_dir(root)
    if not os.path.isdir(folder):
        return []

    items = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []

    for name in names:
        if not name.endswith(".jsonl"):
            continue
        aid = name[:-6]
        if not valid_archive_id(aid):
            continue
        path = os.path.join(folder, name)
        try:
            size = os.path.getsize(path)
            count = _count_lines(path)
        except OSError:
            continue
        items.append((aid, path, size, count))

    items.sort(key=lambda x: x[0], reverse=True)
    return items


def _count_lines(path):
    n = 0
    try:
        with open(path, encoding="utf-8") as f:
            for _ in f:
                n += 1
    except OSError:
        return 0
    return n


def read_archive(archive_id, root=None):
    """读一个归档，返回消息列表。读不到返回空列表。"""
    if not valid_archive_id(archive_id):
        return []
    path = os.path.join(context_dir(root), str(archive_id) + ".jsonl")
    if not os.path.isfile(path):
        return []

    messages = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return messages


# ---------------------------------------------------------------- 检索

def _snippet(text, keyword, radius=None):
    if radius is None:
        radius = _max_snippet_chars() // 2
    """在 text 里找 keyword，截一段上下文出来。"""
    if not text:
        return ""
    text = str(text)
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - radius // 2)
    end = min(len(text), idx + len(keyword) + radius // 2)
    piece = text[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + piece + suffix


def recall(text, archive_id=None, root=None, max_chars=None):
    if max_chars is None:
        max_chars = _max_recall_chars()
    """在归档里做关键词检索。

    返回 (结果文本, 错误信息)。
    """
    keyword = (text or "").strip()
    if not keyword:
        return None, "缺少 text 参数，请给出要查找的关键词。"

    if archive_id:
        if not valid_archive_id(archive_id):
            return None, "归档编号格式不对，应形如 20261022-153000。收到：%s" % archive_id
        archives = [(archive_id, os.path.join(context_dir(root), archive_id + ".jsonl"), 0, 0)]
        if not os.path.isfile(archives[0][1]):
            available = [a[0] for a in list_archives(root)[:5]]
            hint = "当前可用归档：%s" % "、".join(available) if available else "当前没有任何归档。"
            return None, "找不到编号为 %s 的归档。%s" % (archive_id, hint)
    else:
        archives = list_archives(root)
        if not archives:
            return None, (
                "还没有任何上下文归档。归档会在执行 /compact 压缩上下文时自动生成。"
            )

    hits = []
    used_chars = 0

    for aid, path, _size, _count in archives:
        messages = read_archive(aid, root)
        for msg in messages:
            seq = msg.get("seq", "?")
            role = msg.get("role", "?")

            # 消息正文
            body = msg.get("content")
            piece = _snippet(body, keyword) if body else ""

            # 工具调用参数里也可能有
            if not piece:
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    args = fn.get("arguments")
                    piece = _snippet(args, keyword) if args else ""
                    if piece:
                        role = "%s/tool_call:%s" % (role, fn.get("name", "?"))
                        break

            if not piece:
                continue

            block = "[归档 %s · 第 %s 条 · %s]\n%s" % (aid, seq, role, piece)
            if used_chars + len(block) > max_chars:
                hits.append("……（结果较多，已达 %d 字符上限，请缩小关键词范围）" % max_chars)
                break
            hits.append(block)
            used_chars += len(block)

    if not hits:
        scope = archive_id or "全部归档"
        return "在%s里没有找到包含「%s」的内容。换个关键词试试。" % (scope, keyword), None

    header = "在 %d 个归档中找到与「%s」相关的内容：\n" % (len(archives), keyword)
    return header + "\n\n".join(hits), None


# ---------------------------------------------------------------- 压缩

class CompactError(Exception):
    """压缩失败。"""


def build_compact_messages(history, system_prompt=None, target_tokens=None):
    """构造压缩用的 messages。

    注意：**不带任何工具**。压缩期间禁止 Function Calling 是硬要求，
    最彻底的做法就是不给模型工具定义。

    target_tokens 是给模型的长度提示。原文很短时不要硬写 5000 token，
    否则压缩后反而更长。
    """
    lines = []
    for i, msg in enumerate(history, 1):
        role = msg.get("role", "?")
        content = msg.get("content")

        if content:
            lines.append("[%d][%s] %s" % (i, role, content))

        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            lines.append(
                "[%d][%s → 调用 %s] %s"
                % (i, role, fn.get("name", "?"), fn.get("arguments", ""))
            )

        if msg.get("tool_call_id"):
            lines.append(
                "[%d][tool 返回 %s] %s"
                % (i, msg.get("tool_call_id"), content or "")
            )

    transcript = "\n".join(lines)

    # 根据原文长度动态给目标字数，避免「原文 500 token、摘要写 5000」这种倒挂。
    # 原则：摘要必须明显短于原文，否则压缩没意义。
    original_tokens = estimate_tokens(transcript)
    if target_tokens is None:
        # 原文的 60%，但不超过全局目标，也不超过原文本身
        target_tokens = int(original_tokens * 0.6)
        target_tokens = min(target_tokens, _target_summary_tokens())

    if target_tokens < 50:
        goal = (
            "\n\n补充说明：本次需要压缩的原文很短（约 %d tokens），"
            "摘要请尽量精简，控制在几十个 tokens 以内即可，只保留关键事实。"
            % original_tokens
        )
    else:
        goal = (
            "\n\n补充说明：本次需要压缩的原文约 %d tokens，"
            "请把摘要控制在约 %d tokens 以内（明显短于原文），"
            "只保留对后续任务真正有用的信息，不要为了凑长度而展开。"
            % (original_tokens, target_tokens)
        )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({
        "role": "user",
        "content": (
            COMPACT_PROMPT + goal
            + "\n\n---\n\n以下是需要压缩的历史上下文：\n\n" + transcript
        ),
    })
    return messages


def validate_summary(text, original_tokens=None):
    """检查摘要是否可用。返回 (是否合格, 原因)。

    original_tokens 传了就额外校验：摘要不该比原文还长 ——
    那样压缩没有意义，反而浪费上下文。
    """
    if not text or not str(text).strip():
        return False, "摘要是空的"

    body = str(text).strip()

    if len(body) < 50:
        return False, "摘要太短（%d 字符），可能没生成成功" % len(body)

    # 明显是报错信息的情况
    lowered = body.lower()
    for bad in ("error:", "traceback", "exception", "http 4", "http 5"):
        if lowered.startswith(bad):
            return False, "摘要看起来是错误信息：%s" % body[:80]

    # 摘要比原文还长，说明这次压缩没意义
    if original_tokens:
        summary_tokens = estimate_tokens(body)
        if summary_tokens >= original_tokens:
            return False, (
                "摘要（约 %d tokens）没有比原文（约 %d tokens）短，"
                "压缩没有意义。这条对话可能本来就短，不需要压缩。"
                % (summary_tokens, original_tokens)
            )

    return True, None


def archive_note(archive_id, when=None):
    """生成追加在摘要末尾的归档说明。"""
    ts = when or time.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "此前上下文已于 %s 完成压缩，原始上下文保存在编号为 %s 的归档文件中。"
        "如需查找历史信息，请使用 recallContext 工具。" % (ts, archive_id)
    )


def build_compacted_history(summary, archive_id, when=None):
    """把摘要变成新的 history。

    结构化两条消息，符合 user/assistant 交替的习惯：
        1. user      摘要 + 归档说明
        2. assistant 确认已知晓

    System Prompt 和工具定义不在 history 里，由 Agent 单独保留。
    """
    content = "【上下文摘要】\n\n%s\n\n---\n\n%s" % (
        summary.strip(),
        archive_note(archive_id, when),
    )
    return [
        {"role": "user", "content": content},
        {"role": "assistant", "content": "已了解上述上下文，可以继续。"},
    ]
