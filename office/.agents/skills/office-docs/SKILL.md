---
name: 生成 Office 文档
description: 生成 Word、Excel、PPT 文档，用 officeDoc 工具调 officecli 完成
---

# 生成 Office 文档

## 工具

只有两个工具：

| 工具 | 用途 |
|---|---|
| `officeHelp` | 查语法。**不确定就先查，不要猜。** |
| `officeDoc` | 执行 officecli 命令，`args` 传参数数组 |

`officecli` 是个单文件 CLI，不用装 Office 也能读写 `.docx` / `.xlsx` / `.pptx`。

## 铁律：不确定就查 help

```
officeHelp(topic="docx paragraph")     查段落有哪些属性
officeHelp(topic="pptx slide")         查幻灯片怎么写
officeHelp(topic="docx set paragraph") 只查 set 能用的属性
```

一次 help 胜过十次猜错重试。

## 三个最小可用流程

### PPT

```
officeDoc(args=["create", "deck.pptx"])

officeDoc(args=["add", "deck.pptx", "/",
                "--type", "slide", "--prop", "title=季度汇报"])

officeDoc(args=["add", "deck.pptx", "/slide[1]",
                "--type", "shape",
                "--prop", "text=营收增长 25%",
                "--prop", "x=2cm", "--prop", "y=5cm",
                "--prop", "size=24"])
```

### Word

```
officeDoc(args=["create", "report.docx"])

officeDoc(args=["add", "report.docx", "/body",
                "--type", "paragraph",
                "--prop", "text=执行摘要", "--prop", "style=Heading1"])

officeDoc(args=["add", "report.docx", "/body",
                "--type", "paragraph",
                "--prop", "text=本季度营收同比增长 25%。"])
```

### Excel

```
officeDoc(args=["create", "data.xlsx"])

officeDoc(args=["set", "data.xlsx", "/Sheet1/A1",
                "--prop", "value=姓名", "--prop", "bold=true"])

officeDoc(args=["set", "data.xlsx", "/Sheet1/A2", "--prop", "value=张三"])
```

## 路径写法

路径是 **1-based**（跟 XPath 一样）：

```
/slide[1]          第 1 页
/slide[1]/shape[2] 第 1 页的第 2 个形状
/body/p[3]         第 3 段
/Sheet1/A1         Excel 的 A1 单元格
```

注意：

- 路径里有方括号，在 shell 里要加引号，但在 `args` 数组里不用，直接写字符串
- PPT 的 `shape[1]` 通常是标题占位符，正文从 `shape[2]` 开始
- 改动可以用 `--id` 形式的稳定路径，插入删除后不会错位

## 常用命令

| 命令 | 作用 |
|---|---|
| `create <文件>` | 新建空文档，类型看扩展名 |
| `add <文件> <父路径> --type <类型> --prop k=v` | 加元素 |
| `set <文件> <路径> --prop k=v` | 改属性 |
| `get <文件> <路径> --json` | 读节点 |
| `view <文件> outline` | 看结构，改完检查用 |
| `view <文件> text` | 抽纯文本 |
| `remove <文件> <路径>` | 删元素 |
| `query <文件> <选择器>` | CSS 式查询 |

## 改完要检查

每次生成或改完，用 `view <文件> outline` 看一眼结构对不对。

```
officeDoc(args=["view", "deck.pptx", "outline"])
```

## 常见坑

| 坑 | 正确做法 |
|---|---|
| 属性写错 | 先 `officeHelp` 查准确名字 |
| shell 里方括号被展开 | 在 `args` 数组里写字符串，不用管 |
| `--prop text=` 里有换行 | 用 `\\n` 转义 |
| 文件被 PowerPoint/WPS 占着 | 先关掉再改 |
| 数字带 `$` 被吞 | 用单引号包起来，或走 batch |

## 进阶

需要批量操作时用 `batch`，一次执行多条命令，原子提交：

```
officeDoc(args=["batch", "data.xlsx", "--commands",
                "[{\"op\":\"set\",\"path\":\"/Sheet1/A1\",\"props\":{\"value\":\"Done\"}}]"])
```
