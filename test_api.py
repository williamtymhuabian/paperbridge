#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试翻译网关是否可用（key 从 config/env.json 读取，不写在命令行里）"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
cfg = json.loads((BASE / "config" / "env.json").read_text(encoding="utf-8"))

import urllib.request
import urllib.error

base = cfg["OPENAI_BASE_URL"].rstrip("/")
url = base + "/chat/completions"
payload = {
    "model": cfg["OPENAI_MODEL"],
    "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
    "max_tokens": 20,
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json",
             "Authorization": "Bearer " + cfg["OPENAI_API_KEY"]},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
        print("HTTP", r.status)
        print("回复:", body["choices"][0]["message"]["content"])
        print("可用")
        sys.exit(0)
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print("响应:", e.read().decode("utf-8", "replace")[:500])
    sys.exit(1)
except Exception as e:
    print("连接失败:", e)
    sys.exit(1)
