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
│  ├─ skills.py           技能发现、注入、创建、按需加载
│  ├─ mcp/                MCP Client
│  │  ├─ config.py        读 .mcp.json
│  │  ├─ runner.py        后台事件循环（同步↔异步桥接）
│  │  ├─ client.py        stdio / streamable_http 会话
│  │  ├─ adapter.py       工具名映射 + 结果归一化
│  │  └─ manager.py       统一管理和故障隔离
│  ├─ llm/
│  │  └─ client.py        流式请求、SSE 解析、tool_calls 分片归并
│  └─ tools/
│     ├─ registry.py      工具注册表与分发
│     ├─ datetime_tools.py  getDate / isLeapYear
│     ├─ file_tools.py     10 个本地文件操作
│     ├─ web_tools.py      fetchWeb
│     ├─ search_tools.py   searchWeb
│     ├─ cli_tools.py      RunCli
│     ├─ office_tools.py   officeDoc / officeHelp
│     ├─ skill_tools.py    loadSkill / createSkill
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
| `Ctrl+M` | 切换模型 |
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

## 19 个工具

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

## Office 文档：officeDoc / officeHelp

底层用 [officecli](D:\LLM\tools\officecli) —— 一个单文件 CLI，不用装 Office 就能读写
`.docx` / `.xlsx` / `.pptx`。

### 为什么只包两个工具

officecli 的命令有几十条子命令、几百个属性（`add` / `set` / `get` / `query` / `view` /
`batch` / `raw` 等）。**给每条子命令各写一个工具，会有几十个工具挤在上下文里，模型反而选不过来**。

所以只包两个：

| 工具 | 作用 |
|---|---|
| `officeDoc` | 统一入口，`args` 传参数数组，原样转发给 officecli |
| `officeHelp` | 专查语法，把官方帮助文档暴露给模型 |

文档里明确写了「不确定属性名就先跑 help」，所以把 help 单独做成工具，让模型有地方查。

### 用法

```python
officeDoc(args=["create", "deck.pptx"])
officeDoc(args=["add", "deck.pptx", "/", "--type", "slide",
                "--prop", "title=季度汇报"])
officeDoc(args=["add", "deck.pptx", "/slide[1]", "--type", "shape",
                "--prop", "text=营收增长 25%", "--prop", "x=2cm", "--prop", "y=5cm"])
officeDoc(args=["view", "deck.pptx", "outline"])
```

`args` 是数组而不是整条命令字符串，因此路径里的 `[` `]`、参数里的空格都不用转义。

### 执行环境

| 项 | 做法 |
|---|---|
| 可执行文件 | 先查 PATH，再找 `D:\LLM\tools\officecli\officecli-win-x64.exe` |
| 常驻进程 | 设 `OFFICECLI_NO_AUTO_RESIDENT=1`，避免留下后台进程占着文件 |
| 立即落盘 | 设 `OFFICECLI_RESIDENT_FLUSH=each`，防止别的程序读到旧内容 |
| 超时 | 默认 60 秒，上限 300 秒 |
| 输出截断 | 4000 字符 |

### 配套技能

`office/skills/office-docs/SKILL.md` 写了三个最小可用流程（PPT / Word / Excel）、
路径写法、常用命令和踩坑清单。模型加载这个技能后就知道该怎么拼命令，
不用每次从零摸索。

### 实测

| 格式 | 验证方式 | 结果 |
|---|---|---|
| PPT | `python-pptx` 读回 | 2 页，标题和正文文字都对 |
| Word | `python-docx` 读回 | 2 段，Heading 1 样式生效 |
| Excel | `officecli get --json` 读回 | 单元格值正确，bold 属性保留 |

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

### createSkill：让模型自己建技能

| 参数 | 说明 |
|---|---|
| `name` | 必需，技能名，同时是目录名 |
| `skillContext` | 必需，`SKILL.md` 的完整内容 |

在 `<项目根>/.agents/skills/<name>/SKILL.md` 生成文件。四条约束：

**1. 技能名格式**

只允许小写字母、数字和连字符，必须以字母或数字开头：

```
✓ my-skill    ✓ notice-v2
✗ MySkill     ✗ my_skill     ✗ ../evil
```

正则 `^[a-z0-9][a-z0-9-]*$` 一条规则同时管住了格式规范和路径穿越 ——
名字里不可能出现 `/` 或 `..`，天然无法逃出技能目录。

**2. 内容校验**

作业要求 `SKILL.md` 必须包含「正确的 YAML Frontmatter、name、description 及正文」，
四项逐条检查，缺任何一项都返回明确提示让模型改，不会落盘：

| 不合法情况 | 处理 |
|---|---|
| `skillContext` 不以 `---` 开头 | 拒绝，给出正确格式示例 |
| YAML 头部缺 `name` | 拒绝 |
| YAML 头部缺 `description` | 拒绝 |
| 只有头部没有正文 | 拒绝 |
| YAML 语法错 | 拒绝，附错误原因 |

**3. 已存在不覆盖**

直接返回提示，附上现有路径，建议先 `deleteDirectory` 或换个名字。原文件一个字节都不动。

**4. 附件目录不归它管**

`references/`、`scripts/` 这些子目录和辅助文件，由模型创建完技能后继续调
`createDirectory`、`createFile` 补。`createSkill` 只管 `SKILL.md`，单一职责。

### 路径安全

读取范围**严格限制在该技能目录内部**。`../../config.ini` 这类越权路径会被拒绝并返回
明确错误，不会读到技能目录外的文件。校验用 `os.path.commonpath` 比对真实路径。

### 新建技能立即生效

`createSkill` 写入文件后会把它追加进内存里的技能列表，`loadSkill` 马上就能查到，
不用重启。同一个列表通过闭包同时传给两个工具，两边看到的是同一份数据。

### 与已有工具协作

`createSkill`、`loadSkill` 和 `RunCli`、`readFile` 等工具平级，都走同一个 `Registry` 分发。
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

## MCP Client

让 Agent 能连外部 MCP Server，把对方的工具当成自己的工具用。

### 配置

在**项目根**（程序启动时的工作目录）放一个 `.mcp.json`：

```json
{
  "mcpServers": {
    "Bazi-MCP": {
      "type": "streamable_http",
      "url": "https://mcp.api-inference.modelscope.net/4a3222faa31a4e/mcp"
    },
    "PetHospitalMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8090/mcp"
    },
    "本地脚本": {
      "type": "stdio",
      "command": "python",
      "args": ["server.py"],
      "env": {"MCP_PORT": "8092"}
    }
  }
}
```

支持两种协议：

| type | 必填 | 说明 |
|---|---|---|
| `streamable_http`（或 `streamable-http`） | `url` | 远程或本地的 HTTP MCP Server |
| `stdio` | `command`、`args` | 本地子进程，走标准输入输出 |

没写 `type` 时按有无 `url` 自动判断。

### 工具命名

MCP 工具统一加服务器前缀，避免和本地 19 个工具撞名：

```
Bazi-MCP__getBaziDetail
PetHospitalMCP__query_pets
```

内部维护 `暴露名 → (服务器名, 原工具名)` 的映射，调用时反查后转发。

### 同步调异步

这是整个实现最关键的地方。

现有 xAgent 全是同步的，而 MCP SDK 全是 async。`Registry.execute()` 是普通函数，没法 `await`。

做法是起一个后台线程常驻一个事件循环：

```
主线程（同步）                      后台线程（异步）
     │                                   │
     ├─ runner.run(coro) ───────────────►│ 事件循环在执行
     │                                   │
     │◄────────────── 结果 ──────────────┤
     │                                   │
```

MCP 会话常驻在这个循环里，不用每次调用都重连。

**为什么不能每次调用起新循环**：`stdio_client` 和 `streamable_http_client` 都是
async context manager，`async with` 退出就断连。每次新建循环等于每次重新握手，
stdio 还要反复启停子进程，很慢。

### 结果归一化

MCP 的 `CallToolResult` 有四种内容形态，统一转成文本给模型：

| 内容类型 | 处理 |
|---|---|
| `TextContent` | 直接取文本 |
| `ImageContent` | 转成 `[图片 image/png，base64 长度 N]` |
| `AudioContent` | 同理 |
| `EmbeddedResource` | 取 uri 和内容 |
| `structuredContent` | 转 JSON 字符串附在后面 |
| `isError=True` | 当错误返回，让模型知道工具执行失败 |

### 故障隔离

每个 Server 独立连接，一个失败只记一笔，不中断其他：

```
Bazi-MCP        连接成功 → 注册 3 个工具
SomeServer      连接超时 → 记录「连接失败：TimeoutError」
AnotherServer   握手失败 → 记录「连接失败：...」
```

结果：19 个本地工具照常可用，连上的 MCP 工具也能用。

### 对外接口

```python
from core.mcp.manager import McpManager

mgr = McpManager(root=os.getcwd())
mgr.connect_all()                # 失败的记进 mgr.notes
mgr.register_into(registry)      # 塞进工具表
mgr.describe()                   # "1/1 个 MCP Server，3 个工具"
mgr.close()                      # 关会话和事件循环
```

`Agent` 会自动做这些，构造函数加了参数：

```python
Agent(auto_load_mcp=True)        # 默认开，启动时自动连
Agent(auto_load_mcp=False)       # 关掉，只测本地工具时用
```

### 退出清理

TUI 的 `on_unmount()` 会调 `agent.close()` 关掉 MCP 会话，不留后台线程。

## 切换模型

按 `Ctrl+M` 弹出模型选择器：

```
┌──────────────────────────────────────────────────┐
│ 选择模型                                          │
│ 输入关键词过滤，↑↓ 选择，回车确认，Esc 取消         │
│ ┌──────────────────────────────────────────────┐ │
│ │ glm                                          │ │
│ └──────────────────────────────────────────────┘ │
│   ● ZhipuAI/GLM-5.2                              │
│     ZhipuAI/GLM-4.7-Flash                        │
│     ZhipuAI/GLM-5.3                              │
│                                                  │
│ 匹配 3 / 38 个模型  当前：Qwen/Qwen3.8-Flash-Next  │
└──────────────────────────────────────────────────┘
```

选中后：

1. **立即生效** —— 重建 Config
2. **写回 `config.ini`** —— 只改 `model` 那一行，注释和 `[search]` 小节原样保留
3. **清空会话历史** —— 避免旧上下文干扰新模型

模型列表从当前接口的 `/v1/models` 拉。拉不到时退回一份内置清单
（都是 ModelScope 上实测可用的），保证选择器永远有东西可选。

## 项目根定位

作业规定项目根是「程序启动时的工作目录」。但实际有个坑：

```
D:\LLM\office\              ← 技能和 .mcp.json 在这
D:\LLM\Agent\xAgent\        ← 程序在这（兄弟目录）
```

从程序目录启动时，往上翻永远找不到配置 —— 它们是**兄弟关系**，不是父子。

所以定位分三级：

| 优先 | 规则 | 场景 |
|---|---|---|
| 1 | 当前目录有 `.agents/skills` 或 `.mcp.json` 就用它 | 符合作业规定 |
| 2 | 往上翻最多 4 层 | 父子目录 |
| 3 | 读上次记住的根 | 兄弟目录 |

第 3 级靠程序目录下的 `.last-project-root` 文件实现。第一次从正确目录启动时会自动记下来，
之后从任何目录启动都能用。**前两级永远优先**，不覆盖作业要求的行为。

## 测试

```
python _test_layers.py     # 24 项：分层是否真正解耦
python _test_agent.py      # 16 项：mock 服务下的完整对话流程
python _test_tui.py        # 24 项：Textual 无头模式下的界面接线
python _test_web.py        # 46 项：searchWeb / fetchWeb 的全部异常路径
python _test_cli.py        # 56 项：RunCli 的参数、超时、截断、编码
python _test_skills.py     # 86 项：技能发现、注入、按需加载、创建、路径安全
python _test_office.py     # 46 项：officeDoc / officeHelp，真实生成三种文档
python _test_mcp.py        # 50 项：配置解析、名字映射、结果归一化、故障隔离、真实连接
python _test_models.py     # 35 项：模型列表、写回配置、项目根定位、选择器
```

`_test_layers.py` 会用 AST 检查 `core/` 里有没有导入 `textual`、`tui/` 里有没有碰网络和文件，
不是靠人肉看代码保证分层。
