"""模型列表：从当前接口拉可用模型，顺便提供筛选和写回配置。

界面切换模型时用这里。核心是 list_models()：调 /v1/models，
拉不到就退回一份内置清单，保证选择器永远有东西可选。
"""
import json
import urllib.error
import urllib.request

# 拉不到接口时用的兜底清单，都是 ModelScope 上实测可用的
FALLBACK_MODELS = [
    "Qwen/Qwen3.8-Flash-Next",
    "ZhipuAI/GLM-5.2",
    "deepseek-ai/DeepSeek-V4.1-Flash-1017",
    "Qwen/Qwen3.5-397B-A17B",
]

LIST_TIMEOUT = 15


class ModelInfo:
    """一个可用模型。"""

    def __init__(self, model_id, owned_by=""):
        self.id = model_id
        self.owned_by = owned_by

    def __repr__(self):
        return self.id


def models_endpoint(config):
    """把 chat/completions 地址换成 models 地址。"""
    base = config.base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/models"
    return base + "/models"


def list_models(config):
    """拉可用模型列表。返回 (ModelInfo 列表, 错误信息)。

    接口不通时返回兜底清单 + 错误信息，让界面仍然可选。
    """
    url = models_endpoint(config)
    headers = {"Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = "Bearer " + config.api_key

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=LIST_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return _fallback("接口返回 HTTP %d" % e.code)
    except urllib.error.URLError as e:
        return _fallback("网络错误：%s" % getattr(e, "reason", e))
    except (TimeoutError, OSError) as e:
        return _fallback("%s: %s" % (type(e).__name__, e))
    except json.JSONDecodeError:
        return _fallback("接口返回的不是合法 JSON")

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return _fallback("接口返回格式不认识")

    models = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        models.append(ModelInfo(mid, str(item.get("owned_by") or "")))

    if not models:
        return _fallback("接口没返回任何模型")

    models.sort(key=lambda m: m.id.lower())
    return models, None


def _fallback(reason):
    return [ModelInfo(m, "内置清单") for m in FALLBACK_MODELS], reason


def filter_models(models, keyword):
    """按关键词过滤，不区分大小写。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return list(models)
    return [m for m in models if kw in m.id.lower()]


def save_model(model_id, filename="config.ini"):
    """把选中的模型写回 config.ini，只改 model 这一行。

    其他内容原样保留，包括注释和 [search] 小节。
    """
    from .config import find_config

    path = find_config(filename)
    if path is None:
        return False, "找不到 config.ini"

    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return False, "读取失败：%s" % e

    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")) or "=" not in stripped:
            continue
        key, _sep, _value = stripped.partition("=")
        if key.strip().lower() == "model":
            lines[i] = "model = %s" % model_id
            changed = True
            break

    if not changed:
        return False, "config.ini 里没有 model 这一行"

    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        return False, "写回失败：%s" % e

    return True, path
