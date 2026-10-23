# xAgent

带 function call 能力的本地 Agent，代码按 `core` + `tui` 分层。

## 为什么这样分层

`core` 只依赖 Python 标准库，不导入任何界面框架。`tui` 只做显示和输入，业务逻辑一行没有。
将来做 Web 版或 Desktop 版，照着 `tui/` 再写一份即可，`core/` 不用动。

```
xAgent/
├─ main.py                入口
├─ config.example.ini     配置模板
├─ core/                  业务逻辑（不依赖界面）
│  ├─ agent.py            编排：模型 + 工具 + 会话历史
│  ├─ config.py           配置读取
│  ├─ llm/
│  │  └─ client.py        流式请求、SSE 解析、tool_calls 分片归并
│  └─ tools/
│     ├─ registry.py      工具注册表与分发
│     ├─ datetime_tools.py  getDate / isLeapYear
│     ├─ file_tools.py     10 个本地文件操作
│     └─ fsutil.py         路径与文本读取的公共辅助
├─ tui/                   终端界面（Textual）
│  ├─ app.py              主应用
│  ├─ events.py           core 事件 → Textual 消息
│  └─ widgets/
│     ├─ chat_log.py      对话记录区
│     └─ prompt_input.py  输入框
└─ interfaces/README.md   界面契约：新界面要实现的 6 个回调
```

## 用法

```
copy config.example.ini config.ini
:: 编辑 config.ini，填 base_url / model / api_key
python main.py
```

不自带界面、只想看工具：

```
python main.py --tools
python main.py --check
```

## 快捷键

| 键 | 作用 |
|---|---|
| `Enter` | 发送 |
| `Ctrl+J` | 输入框内换行 |
| `Ctrl+N` | 新会话（清空历史） |
| `Ctrl+L` | 清屏 |
| `F1` | 显示工具清单 |
| `Ctrl+C` | 退出 |

## 12 个工具

时间与历法：

- `getDate` —— 调本地 `date` 命令取当前日期时间。
- `isLeapYear` —— 纯 Python 取模判断闰年。

本地文件操作：

- `getCurrentDirectory` —— 当前工作目录
- `listDirectory` —— 列目录，可选递归
- `getFileType` —— 文件类型、MIME、是否纯文本
- `readFile` —— 读纯文本，支持 UTF-8 / GBK
- `createFile` —— 新建文本文件
- `editFile` —— 改文件，`overwrite` / `append`
- `createDirectory` —— 建目录
- `deleteDirectory` —— 删目录（非空也删）
- `deleteFile` —— 删文件
- `renamePath` —— 重命名或移动

## 设计要点

**两种工具实现方式对照**：`getDate` 必须调本地命令（Windows 没有取时间的 Python 内置接口），
其余 11 个全是纯 Python。文件操作如果改成调命令行，`dir` 要正则切表格、`rd /s /q` 返回值不明确，
只会让代码更长更脆。

**界面用线程跑网络**：Agent 的 `ask()` 是阻塞的，TUI 里用 `run_worker(thread=True)` 扔到工作线程，
否则界面会冻结。

**错误整轮回滚**：请求失败时删掉这一轮追加的所有消息，而不是只删最后一条 ——
否则会留下没有对应 `tool` 响应的 `assistant.tool_calls`，下一轮请求必然被服务端拒绝。

**流式 tool_calls 按 index 归并**：分片可能一次只给 id、下一次只给 arguments 的一小段，
必须攒齐再执行。

## 测试

```
python _test_layers.py     # 24 项：分层是否真正解耦
python _test_agent.py      # 16 项：mock 服务下的完整对话流程
python _test_tui.py        # 11 项：Textual 无头模式下的界面接线
```

`_test_layers.py` 会用 AST 检查 `core/` 里有没有导入 `textual`、`tui/` 里有没有碰网络和文件，
不是靠人肉看代码保证分层。
