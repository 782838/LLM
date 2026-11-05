"""模型选择与项目根定位的测试。

分三块：
    一、core/models.py  —— 列表拉取、过滤、写回配置
    二、core/project.py —— 项目根定位（cwd / 往上翻 / 记住的兄弟目录）
    三、界面 —— 选择器弹出、过滤、选中、切换
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")

from core import models as models_mod
from core import project as project_mod
from core.config import Config

passed = 0
failed = []


def check(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("OK   %s" % label)
    else:
        failed.append(label)
        print("FAIL %s  %s" % (label, detail))


print("=" * 72)
print("一、模型列表")
print("=" * 72)

m1 = models_mod.ModelInfo("Qwen/Qwen3.8-Flash-Next")
check("ModelInfo 能构造", m1.id == "Qwen/Qwen3.8-Flash-Next")
check("repr 是 id", repr(m1) == "Qwen/Qwen3.8-Flash-Next", repr(m1))

# endpoints
cfg = Config("https://api-inference.modelscope.cn/v1", "m")
check("models_endpoint 正确",
      models_mod.models_endpoint(cfg) == "https://api-inference.modelscope.cn/v1/models",
      models_mod.models_endpoint(cfg))

# 过滤
pool = [models_mod.ModelInfo(x) for x in
        ["Qwen/Qwen3.8-Flash-Next", "ZhipuAI/GLM-5.2", "deepseek-ai/DeepSeek-V4-Pro"]]

check("空关键词返回全部", len(models_mod.filter_models(pool, "")) == 3)
check("过滤 qwen", len(models_mod.filter_models(pool, "qwen")) == 1)
check("过滤不区分大小写", len(models_mod.filter_models(pool, "QWEN")) == 1)
check("过滤 glm", len(models_mod.filter_models(pool, "glm")) == 1)
check("过滤无匹配返回空", len(models_mod.filter_models(pool, "zzzz")) == 0)

# 拉不到时退回兜底清单
bad_cfg = Config("http://127.0.0.1:1/v1", "m")
fb, note = models_mod.list_models(bad_cfg)
check("接口不通时返回兜底清单", len(fb) > 0, str(len(fb)))
check("兜底时带错误说明", note is not None, str(note))

print()
print("=" * 72)
print("二、写回配置")
print("=" * 72)

SANDBOX = tempfile.mkdtemp(prefix="modelcfg_")
CFG = os.path.join(SANDBOX, "config.ini")

with open(CFG, "w", encoding="utf-8", newline="\n") as f:
    f.write(
        "base_url = https://x/v1\n"
        "model = 旧模型\n"
        "api_key = sk-test\n"
        "\n"
        "[search]\n"
        "baidu_qianfan_api_key = bce-xxx\n"
    )

ok, detail = models_mod.save_model("新模型", filename=CFG)
check("写回成功", ok, detail)

text = open(CFG, encoding="utf-8").read()
check("model 行已更新", "model = 新模型" in text, text[:120])
check("base_url 没动", "base_url = https://x/v1" in text)
check("api_key 没动", "api_key = sk-test" in text)
check("[search] 小节保留", "[search]" in text and "bce-xxx" in text)
check("注释外的空行保留", text.count("\n") >= 5, str(text.count("\n")))

# 不存在的配置文件
ok2, detail2 = models_mod.save_model("x", filename=os.path.join(SANDBOX, "nope.ini"))
check("配置不存在时报错", not ok2, detail2)

shutil.rmtree(SANDBOX, ignore_errors=True)

print()
print("=" * 72)
print("三、项目根定位")
print("=" * 72)

ROOT = tempfile.mkdtemp(prefix="projroot_")
# 造一个带标记的项目根
os.makedirs(os.path.join(ROOT, ".agents", "skills"), exist_ok=True)
with open(os.path.join(ROOT, ".mcp.json"), "w", encoding="utf-8") as f:
    json.dump({"mcpServers": {}}, f)

# 造一个子目录
SUB = os.path.join(ROOT, "a", "b", "c")
os.makedirs(SUB, exist_ok=True)

root, note = project_mod.find_project_root(ROOT)
check("根目录自己有标记时直接用", root == os.path.abspath(ROOT), root)
check("说明是当前目录", "当前目录" in note, note)

root, note = project_mod.find_project_root(SUB)
check("从子目录往上找到根", root == os.path.abspath(ROOT), root)
check("说明提到了向上", "向上" in note, note)

# 完全没有标记时，返回原始目录
# 先清掉记忆，否则会被前面 remember_root 记录的值召回 —— 那是设计行为
_state0 = project_mod._state_path()
if os.path.isfile(_state0):
    os.remove(_state0)

EMPTY = tempfile.mkdtemp(prefix="noproj_")
root, note = project_mod.find_project_root(EMPTY)
check("都没有标记时返回原目录", root == os.path.abspath(EMPTY), root)
check("说明提示没找到", "没找到" in note, note)

# 记住/召回
project_mod.remember_root(ROOT)
check("remember_root 成功", project_mod.recalled_root() == os.path.abspath(ROOT),
      str(project_mod.recalled_root()))

# 兄弟目录场景：从另一个没标记的目录启动，应该召回
sibling = tempfile.mkdtemp(prefix="sibling_")
root, note = project_mod.find_project_root(sibling)
check("兄弟目录能召回上次的根", root == os.path.abspath(ROOT), root)
check("说明提到上次使用", "上次" in note, note)

shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(EMPTY, ignore_errors=True)
shutil.rmtree(sibling, ignore_errors=True)

# 清理状态文件，别影响后面
_state = project_mod._state_path()
if os.path.isfile(_state):
    os.remove(_state)

print()
print("=" * 72)
print("四、界面选择器")
print("=" * 72)

from core.agent import Agent
from tui.app import XAgentApp
from tui.model_picker import ModelPicker


class FakeAgent(Agent):
    def __init__(self):
        super().__init__(auto_load_skills=False, auto_load_mcp=False)

    def ask(self, text):
        return "假回答"


async def ui_test():
    app = XAgentApp(agent=FakeAgent())

    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        check("应用启动", app.is_running)

        pool = [
            models_mod.ModelInfo("Qwen/Qwen3.8-Flash-Next"),
            models_mod.ModelInfo("ZhipuAI/GLM-5.2"),
            models_mod.ModelInfo("deepseek-ai/DeepSeek-V4.1-Flash-1017"),
        ]
        picked = {}

        def on_pick(value):
            picked["value"] = value

        app.push_screen(ModelPicker(pool, "ZhipuAI/GLM-5.2"), on_pick)
        await pilot.pause()

        picker = app.screen
        check("选择器弹出", isinstance(picker, ModelPicker), type(picker).__name__)
        check("列出全部", len(picker._shown) == 3, str(len(picker._shown)))

        inp = picker.query_one("#picker-filter")
        inp.value = "zhipu"
        await pilot.pause()
        check("过滤生效", len(picker._shown) == 1, str(len(picker._shown)))
        check("过滤结果对", picker._shown[0].id == "ZhipuAI/GLM-5.2")

        inp.value = ""
        await pilot.pause()
        check("清空恢复", len(picker._shown) == 3)

        await pilot.press("escape")
        await pilot.pause()
        check("Esc 关闭", not isinstance(app.screen, ModelPicker))
        check("取消回 None", picked.get("value") is None)

        picked.clear()
        app.push_screen(ModelPicker(pool, ""), on_pick)
        await pilot.pause()
        app.screen.dismiss("Qwen/Qwen3.8-Flash-Next")
        await pilot.pause()
        check("选中回传", picked.get("value") == "Qwen/Qwen3.8-Flash-Next")

    return


asyncio.run(ui_test())

print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (passed, len(failed)))
if failed:
    for f in failed:
        print("  失败:", f)
sys.exit(1 if failed else 0)
