# LLM 应用开发课程作业

六次课的动手作业，一个目录一次任务。

- **PetHospitalMCP** —— 宠爱AI病历管理系统：Go 后端存病历，Python MCP 服务器把它包装成工具给 AI 调用。
- **AnythingLLMMCP** —— 把 AnythingLLM 工作区的检索问答接成 MCP 工具。
- **AnythingLLMServer** —— 单文件网页上传文档，让 AnythingLLM 完成向量化。
- **Agent/Practice01** —— `chat.py`，和大模型循环对话：流式打字机输出，每轮把全部聊天记录发给模型。
- **Agent/Practice02** —— `chat.py`，在 Practice01 基础上加 function call：模型自己决定调工具，共 12 个函数。
- **Agent/xAgent** —— 把 Practice02 改造成 `core` + `tui` 两层：业务逻辑不依赖界面，终端界面用 Textual。

Practice01 / Practice02 用法：复制 `config.example.ini` 为 `config.ini`，填自己的接口地址、模型名、密钥，然后 `python chat.py`。

Practice02 的工具故意用两种实现方式对照：`getDate` 走 `subprocess` 调本地 `date` 命令（Windows 没有取时间的 Python 内置接口），其余 11 个都是纯 Python 实现。

xAgent 用法：同样复制 `config.example.ini` 为 `config.ini`，然后 `python main.py`。它的 `core/` 不导入 textual 或任何界面框架，将来加 Web / Desktop 版只需再写一个界面层。

## Practice02 的工具清单

时间与历法：

- `getDate` —— 调本地 `date` 命令取当前日期时间，可传格式化串。
- `isLeapYear` —— 取模判断闰年，不传年份时用本机当前年份。

本地文件操作（10 个）：

- `getCurrentDirectory` —— 取当前工作目录的绝对路径。
- `listDirectory` —— 列出目录内容，标出文件/目录和大小，可选递归。
- `getFileType` —— 按扩展名给出类型名、MIME，并判断是否纯文本。
- `readFile` —— 读纯文本文件内容，默认最多 200 行，支持 UTF-8 和 GBK。
- `createFile` —— 新建文本文件并写初始内容，已存在时默认不覆盖。
- `editFile` —— 修改已有文件，`overwrite` 整体替换、`append` 追加末尾。
- `createDirectory` —— 建目录，父目录自动创建。
- `deleteDirectory` —— 删目录，非空也连内容一起删。
- `deleteFile` —— 删单个文件。
- `renamePath` —— 重命名或移动文件、目录。

## 架构图

`Agent/Practice02/chat-stream-tool-fileOps.mmd` 是这个程序的 Mermaid 架构图，把启动、工具声明、常量配置、工具实现、分发、主循环六层画在一起。

渲染效果：

![Practice02 架构图](Agent/Practice02/chat-stream-tool-fileOps.架构图.jpg)

图片是 `chat-stream-tool-fileOps.mmd` 用 <https://mermaid.live> 渲染后导出的。想改图就改 `.mmd` 文件，再把内容贴到 mermaid.live 重新导出。

## 文件命名

`Agent/Practice02` 下按课程推进保留了几个阶段的快照：

- `chat-stream-tool-getDate.py` —— 只有 `getDate` 一个工具。
- `chat-stream-tool-isLeapYear.py` —— 加上 `isLeapYear`。
- `chat-stream-tool-fileOps.py` —— 加上 10 个文件操作工具，是当前完整版。
- `chat.py` —— 与 `chat-stream-tool-fileOps.py` 内容一致，`启动本地模型.bat` 跑的是它。
