"""MCP Client：把外部 MCP Server 的工具接进 xAgent。

分层
----
    config.py    读 .mcp.json
    runner.py    后台事件循环，把 async 转成同步（现有 Agent 是同步的）
    client.py    连 Server、列工具、调工具
    adapter.py   工具名映射 + 结果归一化

设计要点
--------
1. 现有 Agent 和 Registry 全是同步的，而 MCP SDK 全 async。
   用 AsyncRunner 在后台线程跑一个事件循环，主线程同步等待结果。
2. 工具名统一加服务器前缀 server__tool，避免和本地 19 个工具撞名。
3. 单个 Server 连不上只记一笔，不影响其他工具。
"""
