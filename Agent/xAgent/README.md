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
│  ├─ app.py              主应用，布局与事件接线
│  ├─ events.py           core 事件 → Textual 消息
│  └─ widgets/
│     ├─ message.py       消息卡片、工具卡片
│     ├─ conversation.py  对话流容器
│     ├─ sidebar.py       左侧边栏
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
| `F2` | 显示技能清单 |
| `Ctrl+C` | 退出 |

## 界面

参照 opencode 的对话流形态重写过，分成三块：

```
┌─────────────────────────────────────────────────────────────┐
│ xAgent — core + tui                          11:52   ⭘     │
├──────────────┬──────────────────────────────────────────────┤
│ 模型          │ ▌ 系统                                        │
│ qwen3-vl:4b   │   输入问题后回车发送                          │
│              │                                              │
│ 工具 16       │ ▌ 你                                          │
│ · getDate    │   1900年是闰年吗？                             │
│ · isLeapYear │                                              │
│ ...          │   ✓ isLeapYear(year=1900)                    │
│              │   └ 1900 年不是闰年，2 月有 28 天……            │
│ 技能 2        │                                              │
│ · 撰写通知    │ ▌ 助手                                        │
│ · 星座运势    │   1900 年不是闰年。                            │
│              │   因为能被 100 整除但不能被 400 整除。           │
│ 会话          │                                              │
│ 2 轮对话      │                                              │
├──────────────┴──────────────────────────────────────────────┤
│ Enter 发送  Ctrl+J 换行  Ctrl+N 新会话  F1 工具  F2 技能      │
└─────────────────────────────────────────────────────────────┘
```

几个设计点：

**消息卡片**：每条消息独立成块，左侧有粗色边区分角色 —— 用户蓝、助手绿、工具紫、错误红、系统黄。

**工具调用卡片**：三态显示。执行中 `⏳` 黄色，成功 `✓` 绿色，失败 `✗` 红色。结果最多显示 3 行，超出的显示「还有 N 行」。

**助手回答用 Markdown 渲染**：流式期间是纯文本（保证能实时看到字在动），结束后按 Markdown 重新渲染，代码块、列表、表格都能正常显示。

**左侧边栏**：模型名、工具清单（前 6 个）、技能清单（前 6 个）、会话轮数。技能加载有问题时用 `!` 标出。

## 16 个工具

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

联网能力：

- `searchWeb` —— 调百度千帆 AI 搜索，返回摘要和参考来源标题、链接。
  API Key 读 `config.ini` 的 `[search]` 小节，不硬编码。
- `fetchWeb` —— 用本地 `curl` 抓网页 HTML，再用 `trafilatura` 提正文转 Markdown。
  保留标题、段落、列表、表格、链接，去掉导航栏、广告、页脚。

### 联网工具的两个要求

`searchWeb` 的 Key 放在 `config.ini`：

```ini
[search]
baidu_qianfan_api_key = 你的千帆APIKey
```

`fetchWeb` 依赖 `trafilatura`（`pip install trafilatura`）。它是**可选依赖**：
没装时 `fetchWeb` 会返回明确的安装提示，不影响其余 14 个工具。
## 命令行执行：RunCli

`RunCli` 让 Agent 能调本机任意 CLI 程序。参数分两部分传：

```
RunCli(command="git", args=["--version"])
RunCli(command="dir", args=[])
RunCli(command="python", args=["-c", "print('hi')"])
```

实现要点：

| 项 | 做法 |
|---|---|
| 执行方式 | `subprocess.run([程序名] + 参数列表, shell=False)` |
| 为什么不用 `shell=True` | 参数里的 `&`、`\|`、`>`、`;` 不会被解释成 shell 语法 |
| 返回值 | 退出码 + 标准输出 + 标准错误，三段式结构化文本 |
| 超时 | 默认 30 秒，可用 `timeout` 调大，上限 120 秒 |
| 输出截断 | stdout / stderr 各 4000 字符，截断时标明原始长度 |
| 编码 | 依次尝试 UTF-8、GBK、GB18030，都不行就宽松解码 |
| 程序查找 | 用 `shutil.which()`，找不到时列出常见可用程序帮模型纠正 |

`args` 传字符串时会当成**单个参数**处理，不按空格切分 —— 一旦切分就等于在做命令拼接。

**这个工具不做命令白名单**，按当前用户权限执行，仅用于受控教学环境。

### 异常处理

两个工具都把错误转成给模型看的文本，而不是抛异常打断对话：

| 情况 | 返回内容 |
|---|---|
| 没配 Key | 说明怎么配 `[search]` 小节 |
| Key 是占位符 | 提示换成真实 Key |
| HTTP 401 / 403 / 429 / 5xx | 分别提示无效、无权限、限流、服务端异常 |
| 网络不可达 / 超时 | 说明具体原因和网址 |
| 域名解析失败 | 提示检查网址 |
| 网页是图片页 / JS 渲染页 | 说明提取不到正文的可能原因 |
| HTML 解析失败 | 带异常类型和原始信息 |
| 正文超长 | 截断并标注「已截断」 |

## Agent Skills：技能动态加载

按 Agent Skills 规范实现，分三步走：启动时只扫元数据、注入 System Prompt、正文按需加载。

### 目录约定

```
<项目根>/.agents/skills/<技能名>/SKILL.md
```

**项目根是程序启动时的用户工作目录**（`os.getcwd()`），不是 python.exe 的安装目录，
也不是代码存放目录。所以在 `D:\LLM\office` 下启动，就读 `D:\LLM\office\.agents\skills\`。

每个技能目录至少包含一个 `SKILL.md`，开头用 YAML Frontmatter 声明 `name` 和 `description`：

```markdown
---
name: 撰写通知
description: 撰写公司内部通知
---

正文规则……
```

两个字段都必需，缺任何一个该技能会被跳过并在提示里说明原因。

### 启动时只读元数据

初始化阶段**只读 name 和 description，不读正文**。正文可能很长，一来就全读进内存没必要，
而且直接塞进 System Prompt 会白占上下文。

### 注入 System Prompt

```
You have access to the following skills:
- `撰写通知`: 撰写公司内部通知.
- `星座运势解读`: 根据星座给出当日运势解读和开运建议.
Use the `loadSkill` tool to load the full instructions of a skill when needed. You can also load additional files referenced by a skill.
```

### loadSkill：正文按需加载

| 参数 | 说明 |
|---|---|
| `name` | 必需，技能名称 |
| `filename` | 可选，附件文件的路径或名称 |

- 只给 `name`：返回该技能 `SKILL.md` 全文
- 同时给 `filename`：读取附件，**不重复返回 SKILL.md**

`filename` 支持三种解释，按顺序尝试：

1. 相对技能目录（如 `references/rules.md`）
2. 项目相对路径（如 `.agents/skills/xxx/refs/a.md`）
3. 绝对路径

只给文件名（不含路径分隔符）时，会在该技能目录里递归搜索。
**同名文件多于一个时返回候选列表**，由模型决定读哪个，不会随便挑一个。

### 路径安全

读取范围**严格限制在该技能目录内部**。`../../config.ini` 这类越权路径会被拒绝并返回
明确错误，不会读到技能目录外的文件。校验用 `os.path.commonpath` 比对真实路径。

### 与已有工具协作

`loadSkill` 和 `RunCli`、`readFile` 等 15 个工具平级，都走同一个 `Registry` 分发。
Agent 主流程一行没改，技能只是多了一个工具、多了一段 System Prompt。


**两种工具实现方式对照**：`getDate` 必须调本地命令（Windows 没有取时间的 Python 内置接口），
其余工具基本是纯 Python。文件操作如果改成调命令行，`dir` 要正则切表格、`rd /s /q` 返回值不明确，
只会让代码更长更脆。

**`fetchWeb` 为什么调 curl 而不用 `urllib`**：作业明确要求用 `subprocess` 调本地 curl。
实现上用参数列表方式传参（`subprocess.run(cmd)`，`cmd` 是列表），**不用 `shell=True`**，
URL 里的 `&`、`?` 等字符不会被 shell 解释，避免命令注入。

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
python _test_tui.py        # 24 项：Textual 无头模式下的界面接线
python _test_web.py        # 46 项：searchWeb / fetchWeb 的全部异常路径
python _test_cli.py        # 56 项：RunCli 的参数、超时、截断、编码
python _test_skills.py     # 53 项：技能发现、注入、按需加载、路径安全
```

`_test_layers.py` 会用 AST 检查 `core/` 里有没有导入 `textual`、`tui/` 里有没有碰网络和文件，
不是靠人肉看代码保证分层。
