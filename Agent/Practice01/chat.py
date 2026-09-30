import json
import sys
import urllib.request

cfg = {}
for line in open("config.ini", encoding="utf-8"):
    if "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip().lower()] = v.strip()

prompt = input("请输入提示词：")
print("---")

headers = {"Content-Type": "application/json"}
if cfg.get("api_key"):
    headers["Authorization"] = "Bearer " + cfg["api_key"]

body = json.dumps(
    {"model": cfg["model"], "messages": [{"role": "user", "content": prompt}], "stream": True}
).encode("utf-8")
resp = urllib.request.urlopen(urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions", body, headers))

for raw in resp:
    line = raw.decode("utf-8").strip()
    if line.startswith("data:") and not line.endswith("[DONE]"):
        piece = json.loads(line[5:]).get("choices", [{}])[0].get("delta", {}).get("content", "")
        if piece:
            sys.stdout.write(piece)
            sys.stdout.flush()
print()
