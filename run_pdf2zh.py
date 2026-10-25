#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pdf2zh 的启动入口：先给翻译层打“参考文献保持原文”补丁，再进入 pdf2zh CLI。
环境变量 TRANSLATE_REFS=1 时关闭补丁（连参考文献一起翻）。
由 translate.py 调用，参数与 pdf2zh 完全一致。"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

if os.environ.get("TRANSLATE_REFS") != "1":
    import refs_skip
    refs_skip.patch()

from pdf2zh.pdf2zh import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
