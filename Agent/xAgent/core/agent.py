"""Agent 编排层：把模型、工具、会话历史串起来。

这一层不导入任何界面库。界面通过订阅事件（on_*）来显示过程，
换成 Web 或 Desktop 时只需实现同样的回调，业务逻辑一行不用改。

事件回调都是可选的，签名如下：

    on_assistant_start()                 一轮回答开始
    on_assistant_delta(text)             流式收到一段正文
    on_assistant_end(text, tool_calls)   正文结束（tool_calls 是拼好的调用列表）
    on_tool_start(name, arguments)       准备执行工具
    on_tool_end(name, result, error)     工具执行完
    on_error(message)                    出错
"""
import json
import os
import threading
import time

from . import agents_md
from . import context as context_mod
from . import session as session_mod
from . import skills as skill_store
from .config import Config
from .llm.client import Client, LLMError, ToolCallBuffer
from .mcp.manager import McpManager
from .settings import settings
from .tools import default_registry



class ToolCall:
    """一次完整的工具调用。"""

    def __init__(self, call_id, name, arguments):
        self.call_id = call_id
        self.name = name
        self.arguments = arguments

    def parsed(self):
        """把 arguments 解析成 dict，解析不了返回空 dict。"""
        try:
            value = json.loads(self.arguments or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def as_message(self):
        """塞回 messages 用的格式。"""
        return {
            "id": self.call_id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments or "{}"},
        }

    def __repr__(self):
        return "ToolCall(%s, %s)" % (self.name, self.arguments[:60])


class Agent:
    """一个有记忆、会用工具的对话代理。"""

    def __init__(self, config=None, registry=None, system_prompt=None,
                 skills_root=None, auto_load_skills=True,
                 auto_load_mcp=True, mcp_manager=None):
        self.config = config or Config("http://127.0.0.1:11437/v1", "")
        self.client = Client(self.config)
        self.history = []

        # 让全局 settings 加载配置文件，各模块的默认参数都从这里读
        settings.load()

        # 上下文监控用：上一次请求的真实 prompt_tokens，和当时的历史估算值
        self.last_prompt_tokens = None
        self.last_hist_tokens = 0

        # 项目根：技能、MCP、归档都按它定位
        from .project import find_project_root

        self.root, _note = find_project_root(skills_root or os.getcwd())

        # 压缩期间禁止普通输入，由界面读这个标记
        self.compacting = False

        # 发现技能。初始化阶段只读 name 和 description，不读正文。
        self.skills = []
        self.skill_notes = []
        if auto_load_skills:
            self.skills, self.skill_notes = skill_store.discover(skills_root)

        # 技能清单注入 System Prompt
        self.system_prompt = skill_store.build_system_prompt(
            self.skills, base_prompt=system_prompt
        )

        # 连 MCP Server。单个失败只记 notes，不影响本地工具。
        self.mcp = mcp_manager
        self.mcp_notes = []
        if self.mcp is None and auto_load_mcp:
            self.mcp = McpManager(root=skills_root)
            self.mcp.connect_all()
        if self.mcp is not None:
            self.mcp_notes = list(self.mcp.notes)

        # 工具表要把技能列表闭包进去，loadSkill 才知道有哪些技能；
        # MCP 工具也在这里一起注册进来。
        self.tools = (
            registry
            if registry is not None
            else default_registry(
                skills=self.skills,
                skills_root=skills_root,
                mcp_manager=self.mcp,
            )
        )


        # 事件回调，界面层按需挂
        self.on_assistant_start = None
        self.on_assistant_delta = None
        self.on_assistant_end = None
        self.on_tool_start = None
        self.on_tool_end = None
        self.on_error = None

        # 会话存档相关
        self.session_id = None        # 当前会话编号，/save 后才有
        self.session_created = None   # 会话创建时间，保存时保留
        self.agents_md_path = None    # 注入过的 AGENTS.md 路径
        self.agents_md_content = None # 注入时的内容，保存会话要用
        self.saved_len = 0            # 上次保存时 history 的长度，用来判断有没有新内容

        # 中断控制：界面在别的线程里 set 这个事件，流式循环会检查
        self._stop_event = threading.Event()
        self.interrupted = False      # 上一次 ask 是否被中断

    # ---- 回调辅助 ----
    def _emit(self, name, *args):
        fn = getattr(self, name, None)
        if fn:
            fn(*args)

    # ---- 会话管理 ----
    def reset(self):
        """清空历史，开新会话。"""
        self.history = []
        self.session_id = None
        self.session_created = None
        self.agents_md_content = None
        self.saved_len = 0
        self.last_prompt_tokens = None
        self.last_hist_tokens = 0

    def start_session(self, inject_agents_md=True):
        """开一个新会话，并按需注入 AGENTS.md。

        返回 (是否注入了 AGENTS.md, 说明)。
        """
        self.reset()
        if not inject_agents_md:
            return False, "已跳过 AGENTS.md"

        ok, note = agents_md.inject(self.history, self.root)
        if ok:
            self.agents_md_path = agents_md.find(self.root)
            self.agents_md_content = self.history[0]["content"]
        return ok, note

    def save_session(self):
        """保存当前会话。返回 (会话 id, 说明)。"""
        if not self.history:
            return None, "当前会话是空的，没有保存"

        # 只有 AGENTS.md 注入、没有真实对话，不值得存
        if not any(m.get("role") == "user"
                   and not str(m.get("content") or "").startswith("[项目说明")
                   for m in self.history):
            return None, "当前会话还没有聊过，没有保存"

        sid, path, err = session_mod.save(
            root=self.root,
            messages=self.history,
            session_id=self.session_id,
            model=self.config.model or "",
            agents_md=self.agents_md_content,
            created=self.session_created,
        )
        if err:
            return None, err

        self.session_id = sid
        self.saved_len = len(self.history)
        if self.session_created is None:
            self.session_created = time.strftime("%Y-%m-%d %H:%M:%S")
        return sid, path

    def has_unsaved(self):
        """有没有还没落盘的新内容。退出时据此决定要不要问。"""
        if not self.history:
            return False
        if not any(m.get("role") == "user"
                   and not str(m.get("content") or "").startswith("[项目说明")
                   for m in self.history):
            return False
        return len(self.history) > self.saved_len

    def turn_count(self):
        """当前会话聊了几轮（真实历史算，不靠界面计数器）。"""
        return session_mod.count_turns(self.history)

    def resume_session(self, session_id):
        """恢复一个已保存的会话。返回 (成功与否, 说明)。"""
        data, err = session_mod.load(self.root, session_id)
        if err:
            return False, err

        self.history = list(data.get("messages") or [])
        self.session_id = data.get("id") or session_id
        self.session_created = data.get("created")
        self.agents_md_content = data.get("agents_md")
        self.saved_len = len(self.history)

        # 换了上下文，之前的 token 记录作废
        self.last_prompt_tokens = None
        self.last_hist_tokens = 0

        turns = session_mod.count_turns(self.history)
        return True, "已恢复会话 %s（%d 轮对话）" % (self.session_id, turns)

    def list_sessions(self):
        """列出所有已保存的会话。"""
        return session_mod.list_all(self.root)

    def messages(self):
        """发给模型的完整消息列表。"""
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.history)
        return msgs

    def tool_names(self):
        return self.tools.names()

    def skill_summary(self):
        """给界面显示的一句话技能摘要。"""
        return skill_store.describe(self.skills)

    def mcp_summary(self):
        """给界面显示的一句话 MCP 摘要。"""
        if self.mcp is None:
            return "无 MCP"
        return self.mcp.describe()

    def close(self):
        """关掉 MCP 会话和后台事件循环。界面退出时调。"""
        if self.mcp is not None:
            return self.mcp.close()
        return []

    # ---- 上下文管理 ----
    def context_usage(self):
        """算当前上下文用量，返回 Usage 对象。"""
        window, is_default = context_mod.resolve_window(self.config)
        usage, hist = context_mod.compute_usage(
            system_prompt=self.system_prompt,
            history=self.history,
            window=window,
            is_default=is_default,
            real_prompt_tokens=self.last_prompt_tokens,
            last_hist_tokens=self.last_hist_tokens,
        )
        return usage

    def can_accept_input(self):
        """能不能接受新提示词。

        两种情况拒绝：
            1. 正在压缩
            2. 上下文超阈值还没压缩
        """
        if self.compacting:
            return False, "正在压缩上下文，请稍候。"
        usage = self.context_usage()
        if usage.should_warn:
            return False, (
                "上下文已用 %s，达到窗口的 %.0f%%，请先执行 /compact 压缩。"
                % (usage.summary(), usage.percent)
            )
        return True, None

    def compact(self, on_event=None):
        """执行上下文压缩。

        on_event 是可选回调，用来把进度告诉界面：
            on_event("archiving")      开始归档
            on_event("summarizing")    开始调 LLM
            on_event("done", result)   成功，result 是包含前后内容的字典
            on_event("failed", msg)    失败

        返回 (成功与否, 说明或结果字典)。

        顺序很重要：
            归档 → 生成摘要 → 校验 → 替换
        任何一步失败都保留原上下文。
        """
        def emit(*args):
            if on_event:
                try:
                    on_event(*args)
                except Exception:
                    pass

        if self.compacting:
            return False, "已经在压缩中了。"

        if not self.history:
            return False, "当前会话没有历史消息，不需要压缩。"

        self.compacting = True
        try:
            return self._do_compact(emit)
        finally:
            self.compacting = False

    def _do_compact(self, emit):
        # ---- 1. 先归档，失败就中止 ----
        emit("archiving")
        archive_id, path, err = context_mod.archive(self.root, self.history)
        if err:
            emit("failed", err)
            return False, "归档失败，已中止压缩：%s" % err

        before_text = self._history_as_text()

        # ---- 2. 调 LLM 生成摘要，不带任何工具 ----
        emit("summarizing")
        before_tokens = context_mod.history_tokens(self.history)
        messages = context_mod.build_compact_messages(
            self.history, system_prompt=self.system_prompt
        )

        summary = ""
        try:
            # tools 传空列表 —— 从机制上禁止压缩期间调用工具
            for delta in self.client.stream(messages, tools=None):
                if delta.content:
                    summary += delta.content
        except LLMError as e:
            emit("failed", str(e))
            return False, "生成摘要失败，原上下文已保留：%s" % e

        # ---- 3. 校验摘要 ----
        ok, reason = context_mod.validate_summary(summary, original_tokens=before_tokens)
        if not ok:
            emit("failed", reason)
            return False, "摘要不可用，原上下文已保留：%s" % reason

        # ---- 4. 替换 history。System Prompt 和工具定义不动 ----
        new_history = context_mod.build_compacted_history(summary, archive_id)
        self.history = new_history

        # 换完上下文，之前的 usage 记录失效
        self.last_prompt_tokens = None
        self.last_hist_tokens = 0

        after_text = self._history_as_text()

        result = {
            "archive_id": archive_id,
            "archive_path": path,
            "before": before_text,
            "after": after_text,
            "summary": summary,
            "before_tokens": context_mod.estimate_tokens(before_text),
            "after_tokens": context_mod.estimate_tokens(after_text),
        }
        emit("done", result)
        return True, result

    def _history_as_text(self):
        """把 history 渲染成可读文本，给对比面板用。"""
        lines = []
        for msg in self.history:
            role = msg.get("role", "?")
            content = msg.get("content")
            if content:
                lines.append("【%s】\n%s" % (role, content))
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                lines.append(
                    "【%s → 调用 %s】\n%s"
                    % (role, fn.get("name", "?"), fn.get("arguments", ""))
                )
        return "\n\n".join(lines)

    # ---- 中断控制 ----
    def request_stop(self):
        """请求中断当前生成。界面线程调，会在下一行流式数据前生效。"""
        self._stop_event.set()

    def clear_stop(self):
        self._stop_event.clear()

    def _stopped(self):
        return self._stop_event.is_set()

    # ---- 主流程 ----
    def ask(self, text):
        """提一个问题，跑完整个「回答-调工具-再回答」循环。

        返回最终的助手文本。出错时返回空串并把错误交给 on_error。
        被 request_stop() 中断时，返回已经生成的部分。
        """
        text = (text or "").strip()
        if not text:
            return ""

        # 每次提问开始先清掉上次的中断标记
        self.clear_stop()
        self.interrupted = False

        self.history.append({"role": "user", "content": text})
        mark = len(self.history) - 1  # 出错时回滚到这里

        try:
            return self._run_loop(mark)
        except LLMError as e:
            # 整轮回滚：不能只弹最后一条，否则会留下没有对应 tool 响应的
            # assistant.tool_calls，下一轮请求必然被服务端拒绝。
            del self.history[mark:]
            self._emit("on_error", str(e))
            return ""

    def _run_loop(self, mark):
        schemas = self.tools.schemas()
        final_text = ""

        for _ in range(settings.max_tool_rounds):
            buffer = ToolCallBuffer()
            answer = ""
            self._emit("on_assistant_start")

            last_usage = None
            for delta in self.client.stream(
                self.messages(), schemas, should_stop=self._stopped
            ):
                if delta.usage:
                    last_usage = delta.usage
                if delta.content:
                    answer += delta.content
                    self._emit("on_assistant_delta", delta.content)
                if delta.tool_calls:
                    buffer.feed(delta.tool_calls)

            # 记下这次请求的真实 token 用量，供上下文监控用
            if last_usage:
                self.last_prompt_tokens = last_usage.get("prompt_tokens")
                self.last_hist_tokens = context_mod.history_tokens(self.history)

            # 被中断了：把已生成的内容保留进历史，不再继续调工具
            if self._stopped():
                self.interrupted = True
                if answer.strip():
                    self.history.append({
                        "role": "assistant",
                        "content": answer + "\n\n（这条回答被用户中断）",
                    })
                else:
                    # 一个字都没生成，把用户那条也撤掉，避免留下空提问
                    del self.history[mark:]
                self._emit("on_assistant_end", answer, [])
                return answer

            calls = [ToolCall(c["id"], c["name"], c["arguments"]) for c in buffer.ready()]
            self._emit("on_assistant_end", answer, calls)

            if not calls:
                self.history.append({"role": "assistant", "content": answer})
                return answer

            self.history.append(
                {
                    "role": "assistant",
                    "content": answer or None,
                    "tool_calls": [c.as_message() for c in calls],
                }
            )

            for call in calls:
                # 工具执行前再查一次 —— 用户可能在工具列表刚下发时就打断了
                if self._stopped():
                    self.interrupted = True
                    self._emit(
                        "on_error",
                        "已中断：还有 %d 个工具没执行。" % len(calls),
                    )
                    return answer

                args = call.parsed()
                self._emit("on_tool_start", call.name, args)
                result, error = self.tools.execute(call.name, args)
                if error:
                    self._emit("on_tool_end", call.name, error, error)
                    content = "工具调用失败：%s" % error
                else:
                    self._emit("on_tool_end", call.name, result, None)
                    content = result
                self.history.append(
                    {"role": "tool", "tool_call_id": call.call_id, "content": content}
                )
            final_text = answer

        # 轮数用完还没收敛，把当前状态告诉调用方
        self._emit(
            "on_error",
            "连续 %d 轮都在调用工具还没给出结论，已停止。可以换个问法。" % settings.max_tool_rounds,
        )
        return final_text
