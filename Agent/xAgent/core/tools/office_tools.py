"""Office 文档工具：把 officecli 包装成 Function Calling 工具。

officecli 是个单文件 CLI，支持 .docx / .xlsx / .pptx 的读写，
不需要装 Office。它的命令语法很丰富（L1 读 → L2 DOM 编辑 → L3 原始 XML），
所以这里只包一个统一入口 `officeDoc`，由模型自己拼参数，
而不是为每个子命令各写一个工具 —— 那样会有几十个工具，模型反而选不过来。

另配一个 `officeHelp` 专门查语法。文档里明确说了：
不确定属性名就先跑 help，比猜错重试快得多。
"""
import os
import shutil
import subprocess

from .registry import Tool

# officecli 打一次命令生成/编辑可能要几秒，给足时间
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300
MAX_OUTPUT_CHARS = 4000

# 常见安装位置的候选路径
EXE_CANDIDATES = (
    r"D:\LLM\tools\officecli\officecli-win-x64.exe",
    r"D:\LLM\tools\officecli\officecli.exe",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "..", "..", "tools", "officecli",
        "officecli-win-x64.exe"),
)


def find_officecli():
    """找 officecli 可执行文件。先看 PATH，再看候选路径。"""
    for name in ("officecli", "officecli.exe", "officecli-win-x64.exe"):
        found = shutil.which(name)
        if found:
            return found
    for path in EXE_CANDIDATES:
        path = os.path.abspath(path)
        if os.path.isfile(path):
            return path
    return None


def decode(raw):
    """命令输出解码。officecli 输出是 UTF-8。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n……（输出过长，已截断）", True


def run_officecli(args, timeout=DEFAULT_TIMEOUT):
    """跑一条 officecli 命令，返回 (stdout, stderr, 退出码, 错误信息)。"""
    exe = find_officecli()
    if not exe:
        return None, None, None, (
            "找不到 officecli。请把 officecli-win-x64.exe 放到 "
            "D:\\LLM\\tools\\officecli\\ 下，或加进 PATH。"
        )

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = max(1, min(timeout, MAX_TIMEOUT))

    env = dict(os.environ)
    # 关掉常驻进程，避免留下后台进程占着文件
    env["OFFICECLI_NO_AUTO_RESIDENT"] = "1"
    # 每条命令都立即落盘，防止后续用别的程序读时读到旧内容
    env["OFFICECLI_RESIDENT_FLUSH"] = "each"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [exe] + [str(a) for a in args]

    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, None, None, "officecli 执行超时（超过 %d 秒），已终止。" % timeout
    except FileNotFoundError:
        return None, None, None, "找不到 officecli 可执行文件：%s" % exe
    except OSError as e:
        return None, None, None, "启动 officecli 失败：%s" % e

    return (
        decode(proc.stdout),
        decode(proc.stderr),
        proc.returncode,
        None,
    )


def format_result(args, stdout, stderr, code):
    """把命令结果拼成给模型看的文本。"""
    head = "命令：officecli " + " ".join(str(a) for a in args)
    lines = [head, "退出码：%d" % code]

    if code == 0:
        lines.append("说明：执行成功。")
    else:
        lines.append("说明：执行失败，请看下面的错误输出。")

    out, cut = truncate((stdout or "").strip())
    lines.append("")
    lines.append("--- 输出 ---")
    if out:
        lines.append(out)
    else:
        lines.append("（空）")

    err = (stderr or "").strip()
    if err:
        err_text, err_cut = truncate(err)
        lines.append("")
        lines.append("--- 错误 ---")
        lines.append(err_text)

    return "\n".join(lines)


def office_doc(args=None, timeout=DEFAULT_TIMEOUT):
    """执行一条 officecli 命令。

    args 是参数数组，原样传给 officecli，例如：
        ["create", "report.docx"]
        ["add", "report.docx", "/body", "--type", "paragraph",
         "--prop", "text=标题", "--prop", "style=Heading1"]

    用数组而不是整条命令字符串，参数里的空格、引号不用转义。
    """
    if not args:
        return (
            "缺少 args 参数。请给出要执行的 officecli 子命令和参数，例如：\n"
            '  ["create", "report.docx"]\n'
            '  ["add", "report.docx", "/body", "--type", "paragraph", '
            '"--prop", "text=你好"]\n'
            "不确定语法时先调 officeHelp 查。"
        )

    if isinstance(args, str):
        return (
            "args 必须是字符串数组，不是一整条命令。"
            "例如 [\"create\", \"report.docx\"]，不要写成 \"create report.docx\"。"
        )

    if not isinstance(args, (list, tuple)):
        return "args 必须是字符串数组，收到的是 %s。" % type(args).__name__

    result = run_officecli(list(args), timeout=timeout)
    stdout, stderr, code, err = result

    if err:
        return "执行失败：%s" % err

    return format_result(args, stdout, stderr, code)


def office_help(topic=None):
    """查 officecli 的语法帮助。"""
    args = ["help"]
    if topic and str(topic).strip():
        args.extend(str(topic).strip().split())

    stdout, stderr, code, err = run_officecli(args, timeout=30)

    if err:
        return "查询帮助失败：%s" % err

    text = (stdout or "").strip()
    if not text:
        text = (stderr or "").strip()
    if not text:
        return "没有查到帮助内容。topic 可以传 docx / xlsx / pptx / 或具体元素名。"

    out, _cut = truncate(text, 6000)
    return out


def build_tools():
    """返回 Office 文档工具。"""
    return [
        Tool(
            name="officeDoc",
            description=(
                "读写 Office 文档（.docx / .xlsx / .pptx），底层调 officecli。"
                "args 传 officecli 的子命令和参数数组，例如 "
                "[\"create\", \"report.docx\"] 或 "
                "[\"add\", \"deck.pptx\", \"/\", \"--type\", \"slide\", "
                "\"--prop\", \"title=标题\"]。"
                "常见子命令：create 新建、add 加元素、set 改属性、get 读节点、"
                "query 查询、remove 删除、view 查看结构、open/close 显式打开保存。"
                "路径是 1-based，比如 /body/p[3] 是第三段、/slide[1] 是第一页。"
                "**不确定属性名或语法时，先调 officeHelp 查，不要猜。**"
                "生成完可用 view <文件> outline 检查结构。"
            ),
            func=office_doc,
            parameters={
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "officecli 的参数数组，第一个元素是子命令。"
                            "例如 [\"create\", \"a.pptx\"]、"
                            "[\"add\", \"a.pptx\", \"/\", \"--type\", \"slide\", "
                            "\"--prop\", \"title=Q4\"]、"
                            "[\"view\", \"a.pptx\", \"outline\"]。"
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 60，最大 300。",
                    },
                },
            },
            required=["args"],
        ),
        Tool(
            name="officeHelp",
            description=(
                "查 officecli 的语法帮助。不确定某个元素有哪些属性、"
                "值该怎么写、命令怎么拼时，先调这个再动手，比猜错重试快得多。\n"
                "topic 传法：\n"
                "  空 → 列出所有命令\n"
                "  \"docx\" / \"xlsx\" / \"pptx\" → 列出该格式所有元素\n"
                "  \"docx paragraph\" → 查段落的全部属性\n"
                "  \"docx set paragraph\" → 只查 set 能用的属性"
            ),
            func=office_help,
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "要查的主题，例如 \"docx paragraph\"、"
                            "\"pptx slide\"、\"xlsx cell\"。不传则列全部命令。"
                        ),
                    }
                },
            },
        ),
    ]
