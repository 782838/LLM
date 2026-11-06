"""项目根定位。

作业规定：项目根是**程序启动时的用户工作目录**（os.getcwd()），
不是 python.exe 安装目录，也不是代码存放目录。

但实际用起来有个坑：技能和 MCP 配置放在 <项目根>/office，
而程序在 <项目根>/Agent/xAgent —— 这是**兄弟目录**，从程序目录启动时
往上翻永远找不到。

所以定位按三级优先：
    1. 当前工作目录有 .agents/skills 或 .mcp.json → 用它（符合作业规定）
    2. 往上翻几层找（父子关系的情况）
    3. 读上次记住的项目根（兄弟目录的情况，靠启动脚本存下来）

第 3 级是兜底，不会覆盖前两级。
"""
import json
import os

MAX_UP_LEVELS = 4

# 判断「这是不是一个项目根」的标记
MARKERS = (os.path.join(".agents", "skills"), ".mcp.json")

# 记住上次用的项目根，放在程序目录下
STATE_FILE = ".last-project-root"


def _has_any_marker(path):
    try:
        return any(os.path.exists(os.path.join(path, m)) for m in MARKERS)
    except OSError:
        return False


def _state_path():
    """状态文件位置：程序自己所在的目录。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, STATE_FILE)


def remember_root(root):
    """记住一个项目根，写进程序目录下的状态文件。"""
    path = _state_path()
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"root": os.path.abspath(root)}, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def recalled_root():
    """读上次记住的项目根，没有或文件坏了返回 None。"""
    path = _state_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        root = str(data.get("root") or "").strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    if root and os.path.isdir(root) and _has_any_marker(root):
        return root
    return None


def _scan_siblings(base, max_depth=2):
    """从 base 往上走两三层，在每一层的兄弟目录里找带标记的。

    处理这种情况：
        <项目根>\\office\\            ← 配置在这
        <项目根>\\Agent\\xAgent\\     ← 程序在这
    xAgent 往上翻找不到 office（兄弟关系），但从 <项目根> 这一层
    往下看一层就能看到 office。

    只扫很浅的层级，且限制目录数量，不会卡住。
    """
    current = base
    for _ in range(max_depth):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

        try:
            entries = sorted(os.listdir(current))
        except OSError:
            continue

        for name in entries[:50]:        # 最多看 50 个兄弟目录
            sibling = os.path.join(current, name)
            if not os.path.isdir(sibling):
                continue
            if _has_any_marker(sibling):
                return sibling
    return None


def find_project_root(start=None, max_up=MAX_UP_LEVELS):
    """定位项目根。返回 (路径, 说明)。"""
    base = os.path.abspath(start or os.getcwd())

    # 1. 当前目录有标记，就用当前目录 —— 这是作业规定的行为
    if _has_any_marker(base):
        remember_root(base)
        return base, "当前目录"

    # 2. 往上翻，处理父子关系的情况
    current = base
    for level in range(1, max_up + 1):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
        if _has_any_marker(current):
            remember_root(current)
            return current, "向上第 %d 层" % level

    # 3. 读上次记住的 —— 处理兄弟目录的情况
    last = recalled_root()
    if last is not None:
        return last, "上次使用的目录（当前目录往上都没有配置）"

    # 4. 扫一遍附近的兄弟目录，找到就记住
    found = _scan_siblings(base)
    if found is not None:
        remember_root(found)
        return found, "在附近的兄弟目录里找到（%s）" % os.path.basename(found)

    return base, "当前目录（没找到技能或 MCP 配置）"
