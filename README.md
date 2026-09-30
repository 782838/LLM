# LLM 应用开发课程作业

四次课的动手作业，一个目录一次任务。

- **PetHospitalMCP** —— 宠爱AI病历管理系统：Go 后端存病历，Python MCP 服务器把它包装成工具给 AI 调用。
- **AnythingLLMMCP** —— 把 AnythingLLM 工作区的检索问答接成 MCP 工具。
- **AnythingLLMServer** —— 单文件网页上传文档，让 AnythingLLM 完成向量化。
- **Agent/Practice01** —— `chat.py`，和大模型循环对话：流式打字机输出，每轮把全部聊天记录发给模型。

Practice01 用法：复制 `config.example.ini` 为 `config.ini`，填自己的接口地址、模型名、密钥，然后 `python chat.py`。
