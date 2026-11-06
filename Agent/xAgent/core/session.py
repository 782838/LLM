"""会话管理：保存、列出、恢复。

一次会话存成一个 JSON 文件：

    <项目根>/.agents/sessions/20261106-110000.json

结构：
    {
      "id": "20261106-110000",
      "created": "2026-11-06 11:00:00",
      "updated": "2026-11-06 11:05:00",
      "model": "deepseek-ai/...",
      "turns": 5,
      "messages": [...],          # 完整的 history
      "agents_md": "..."          # 注入过的 AGENTS.md 内容，恢复时不再重复读
    }

为什么要存 agents_md：任务要求「一次注入，全程复用」。
恢复会话时如果重新读一遍 AGENTS.md，内容可能已经变了，
历史里那条注入消息就和文件对不上。存下来最稳。
"""
import json
import os
import time

from .settings import settings

# 一个会话文件最多多大，超了不列出来（避免列表被巨型会话拖慢）
MAX_SESSION_BYTES = 20 * 1024 * 1024

# 列表里显示的摘要长度
PREVIEW_CHARS = 60


class SessionError(Exception):
    """会话操作失败。"""


def sessions_dir(root=None):
    """会话目录的绝对路径。"""
    base = root or os.getcwd()
    # 配置里的路径可能用正斜杠，统一用系统分隔符
    parts = settings.session_dir.replace("\\", "/").split("/")
    return os.path.join(base, *[p for p in parts if p])


def new_id(now=None):
    """生成会话 id：20261106-110000。"""
    return time.strftime("%Y%m%d-%H%M%S", now or time.localtime())


def _ensure_dir(root):
    folder = sessions_dir(root)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise SessionError("创建会话目录失败：%s" % e)
    return folder


def preview_of(messages, limit=PREVIEW_CHARS):
    """从 messages 里挑一句用户说的话做摘要。"""
    for msg in messages or []:
        if msg.get("role") == "user":
            text = str(msg.get("content") or "").strip()
            if not text:
                continue
            # 跳过 AGENTS.md 注入的那条
            if text.startswith("[项目说明"):
                continue
            text = " ".join(text.split())
            return text[:limit] + ("…" if len(text) > limit else "")
    return "（空会话）"


def count_turns(messages):
    """数一下用户发过几轮。"""
    return sum(1 for m in messages or [] if m.get("role") == "user"
               and not str(m.get("content") or "").startswith("[项目说明"))


def save(root, messages, session_id=None, model="", agents_md=None,
         created=None, now=None):
    """保存一次会话。

    返回 (会话 id, 文件路径, 错误信息)。成功时错误信息为 None。
    """
    if not messages:
        return None, None, "没有可保存的消息"

    folder = _ensure_dir(root)
    sid = session_id or new_id(now)
    path = os.path.join(folder, sid + ".json")

    stamp = time.strftime("%Y-%m-%d %H:%M:%S", now or time.localtime())

    # 已经存在就保留原来的创建时间
    old_created = created
    if old_created is None and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                old_created = json.load(f).get("created")
        except (OSError, json.JSONDecodeError):
            old_created = None

    data = {
        "id": sid,
        "created": old_created or stamp,
        "updated": stamp,
        "model": model or "",
        "turns": count_turns(messages),
        "preview": preview_of(messages),
        "agents_md": agents_md,
        "messages": messages,
    }

    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError as e:
        return None, None, "写会话文件失败：%s" % e

    return sid, path, None


def load(root, session_id):
    """读一个会话，返回 (数据字典, 错误信息)。"""
    if not session_id:
        return None, "缺少会话编号"

    path = os.path.join(sessions_dir(root), str(session_id) + ".json")
    if not os.path.isfile(path):
        return None, "找不到会话 %s" % session_id

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return None, "会话文件不是合法 JSON：%s" % e
    except OSError as e:
        return None, "读取会话失败：%s" % e

    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return None, "会话文件结构不对，缺少 messages"

    return data, None


class SessionInfo:
    """会话列表里的一项。"""

    def __init__(self, session_id, path, size, created, updated,
                 turns, preview, model):
        self.id = session_id
        self.path = path
        self.size = size
        self.created = created
        self.updated = updated
        self.turns = turns
        self.preview = preview
        self.model = model

    def label(self):
        """列表里显示的一行。"""
        return "%s  %s（%d 轮）" % (self.updated or self.id, self.preview, self.turns)

    def __repr__(self):
        return "SessionInfo(%s, %d 轮)" % (self.id, self.turns)


def list_all(root=None):
    """列出所有会话，新的在前。"""
    folder = sessions_dir(root)
    if not os.path.isdir(folder):
        return []

    items = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []

    for name in names:
        if not name.endswith(".json"):
            continue
        sid = name[:-5]
        path = os.path.join(folder, name)
        try:
            size = os.path.getsize(path)
            if size > MAX_SESSION_BYTES:
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        items.append(SessionInfo(
            session_id=sid,
            path=path,
            size=size,
            created=data.get("created") or "",
            updated=data.get("updated") or "",
            turns=data.get("turns") or 0,
            preview=data.get("preview") or "（无摘要）",
            model=data.get("model") or "",
        ))

    items.sort(key=lambda s: (s.updated, s.id), reverse=True)
    return items


def delete(root, session_id):
    """删一个会话。返回 (成功与否, 错误信息)。"""
    path = os.path.join(sessions_dir(root), str(session_id) + ".json")
    if not os.path.isfile(path):
        return False, "找不到会话 %s" % session_id
    try:
        os.remove(path)
    except OSError as e:
        return False, "删除失败：%s" % e
    return True, None
