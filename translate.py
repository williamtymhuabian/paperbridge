#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
论文翻译工具（封装 pdf2zh / PDFMathTranslate）
用法：
    python translate.py 单篇.pdf
    python translate.py 目录/            # 批量翻译目录下所有 pdf
    python translate.py 文件.pdf --fresh # 绕过缓存强制重翻（改术语表后必须加）

产出（output/ 下两份）：
    xxx-mono.pdf  纯中文版（版面与原 PDF 一致）
    xxx-dual.pdf  双语对照版（原文页 + 中文页交替）

参考文献处理（默认开启，--translate-refs 可关）：
    自动定位 References 起始页：之前的页正常翻译；References 标题所在页
    用条目启发式跳过引用条目；其后的页（含附录）整页保持原文，最后拼回
    一份完整 PDF。页面切分保证绝不误伤正文。
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_DIR = BASE / "config"
OUT_DIR = BASE / "output"
LOG_DIR = BASE / "logs"
CACHE_DIR = BASE / ".cache"

DEFAULT_GLOSSARY = "VLA->VLA,VLN->VLN"


def load_env():
    return json.loads((CONFIG_DIR / "env.json").read_text(encoding="utf-8"))


def build_prompt(glossary_csv: Path, template: Path) -> Path:
    """把术语表渲染进 prompt 模板，产出最终 prompt 文件。"""
    rows = []
    if glossary_csv.exists():
        with glossary_csv.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                term = (row.get("term") or "").strip()
                trans = (row.get("译法") or "").strip()
                if term and trans:
                    rows.append(f"{term} = {trans}")
    if not rows:
        rows = [DEFAULT_GLOSSARY]
    text = template.read_text(encoding="utf-8")
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    out_path = CACHE_DIR / "prompt.txt"
    out_path.write_text(text.replace("{glossary}", "\n".join(rows)), encoding="utf-8")
    return out_path


def pdf2zh_cli() -> Path:
    venv_py = BASE / ".venv" / "Scripts" / "python.exe"
    return venv_py if venv_py.exists() else Path(sys.executable)


def run_pdf2zh(pdf: Path, outdir: Path, env: dict, prompt_file: Path,
               threads: int, fresh: bool, pages: str = None) -> tuple:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(pdf2zh_cli()), str(BASE / "run_pdf2zh.py"), str(pdf),
        "-li", env.get("lang_in", "en"),
        "-lo", env.get("lang_out", "zh"),
        "-s", env.get("engine", "openai"),
        "-t", str(threads),
        "-o", str(outdir),
        "--prompt", str(prompt_file),
    ]
    if pages:
        cmd += ["--pages", pages]
    if fresh:   # 绕过缓存；改了术语表/补丁后必须加，否则旧译文直接复用
        cmd += ["--ignore-cache"]

    proc_env = os.environ.copy()
    proc_env["HF_ENDPOINT"] = "https://hf-mirror.com"
    proc_env["PYTHONIOENCODING"] = "utf-8"
    if os.environ.get("TRANSLATE_REFS") == "1":
        proc_env["TRANSLATE_REFS"] = "1"
    for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        if env.get(k):
            proc_env[k] = str(env[k])

    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(BASE), env=proc_env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + "\n" + r.stderr, time.time() - t0


def find_refs_start(pdf: Path) -> int | None:
    """预扫描：定位 References 标题所在页（1-based）。找不到返回 None。"""
    try:
        import fitz
    except ImportError:
        return None
    doc = fitz.open(str(pdf))
    try:
        for i, page in enumerate(doc):
            for b in page.get_text("blocks"):
                t = (b[4] or "").strip().rstrip(": ").lower()
                if t in ("references", "bibliography", "literature cited"):
                    return i + 1
        return None
    finally:
        doc.close()


def stitch(part_a: Path, part_b: Path, refs_from: int, out_mono: Path, out_dual: Path):
    """拼接最终文档。
    pdf2zh 的 --pages 只控制"翻哪些页"，输出仍含全部页（未翻页保持原样）：
      A = --pages "1..refs_from-1"（正文译文，其后页原样）
      B = --pages "refs_from"（References 标题页，条目启发式跳过）
    mono = A 的正文页 + B 的标题页 + A 的其后原样页
    dual = A 的 [原,译] 交替 + B 的 [原,译] + A 的尾部原样
    页码均为 0-based 取页。"""
    import fitz
    A, B = fitz.open(str(part_a["mono"])), fitz.open(str(part_b["mono"]))
    Ad, Bd = fitz.open(str(part_a["dual"])), fitz.open(str(part_b["dual"]))

    mono = fitz.open()
    mono.insert_pdf(A, from_page=0, to_page=refs_from - 2)
    mono.insert_pdf(B, from_page=refs_from - 1, to_page=refs_from - 1)
    mono.insert_pdf(A, from_page=refs_from, to_page=len(A) - 1)
    mono.save(str(out_mono))
    mono.close()

    dual = fitz.open()
    dual.insert_pdf(Ad, from_page=0, to_page=2 * (refs_from - 1) - 1)
    dual.insert_pdf(Bd, from_page=2 * (refs_from - 1), to_page=2 * (refs_from - 1) + 1)
    dual.insert_pdf(Ad, from_page=2 * refs_from, to_page=len(Ad) - 1)
    dual.save(str(out_dual))
    dual.close()


def translate_one(pdf: Path, env: dict, prompt_file: Path, outdir: Path,
                  threads: int, fresh: bool, keep_refs: bool) -> tuple:
    """返回 (returncode, 合并日志, 用时)。"""
    stem = pdf.stem
    t0 = time.time()
    logs = []
    code = 0

    refs_from = None if keep_refs else find_refs_start(pdf)
    if refs_from and refs_from >= 2:
        with tempfile.TemporaryDirectory(prefix="p2z_", dir=str(CACHE_DIR)) as td:
            tdp = Path(td)
            part_a = {"mono": tdp / f"{stem}-mono.pdf", "dual": tdp / f"{stem}-dual.pdf"}
            part_b = {"mono": tdp / "b" / f"{stem}-mono.pdf", "dual": tdp / "b" / f"{stem}-dual.pdf"}

            c1, l1, _ = run_pdf2zh(pdf, tdp, env, prompt_file, threads, fresh,
                                   pages=f"1-{refs_from - 1}")
            logs.append(f"--- 正文(1-{refs_from - 1} 页) exit={c1}\n{l1[-800:]}")
            c2, l2, _ = run_pdf2zh(pdf, tdp / "b", env, prompt_file, threads, fresh,
                                   pages=str(refs_from))
            logs.append(f"--- References标题页({refs_from}) exit={c2}\n{l2[-800:]}")
            if c1 == 0 and c2 == 0 and part_a["mono"].exists() and part_b["mono"].exists():
                outdir.mkdir(parents=True, exist_ok=True)
                stitch(part_a, part_b, refs_from,
                       outdir / f"{stem}-mono.pdf", outdir / f"{stem}-dual.pdf")
                logs.append(f"--- 拼接完成：1-{refs_from - 1} 译文 + {refs_from} 混合页 + "
                            f"{refs_from + 1}-末页 原文")
            else:
                code = c1 or c2 or 1
                logs.append("--- 分片翻译失败")
    else:
        if refs_from is None:
            logs.append("--- 未定位到 References 标题，整篇翻译（条目启发式兜底）")
        code, log, _ = run_pdf2zh(pdf, outdir, env, prompt_file, threads, fresh)
        logs.append(log)
    return code, "\n".join(logs), time.time() - t0


def main():
    ap = argparse.ArgumentParser(description="论文全文翻译（保留排版/公式/图片位置）")
    ap.add_argument("input", help="PDF 文件或含 PDF 的目录")
    ap.add_argument("-o", "--outdir", default=str(OUT_DIR), help="输出目录")
    ap.add_argument("-t", "--threads", type=int, default=None, help="并发线程数")
    ap.add_argument("--resume", action="store_true", help="跳过输出目录里已存在成果的文件")
    ap.add_argument("--fresh", action="store_true", help="强制重翻（绕过缓存）；改术语表后想生效必须加")
    ap.add_argument("--translate-refs", action="store_true", help="连参考文献也翻译（默认保持原文）")
    ap.add_argument("--limit", type=int, default=0, help="只翻译前 N 个（调试用）")
    args = ap.parse_args()

    env = load_env()
    prompt_file = build_prompt(CONFIG_DIR / "术语表.csv", CONFIG_DIR / "prompt-template.txt")
    outdir = Path(args.outdir)
    LOG_DIR.mkdir(exist_ok=True, parents=True)
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    keep_refs = args.translate_refs or os.environ.get("TRANSLATE_REFS") == "1"

    src = Path(args.input)
    if src.is_file():
        pdfs = [src]
    else:
        pdfs = sorted(src.rglob("*.pdf"))
        pdfs = [p for p in pdfs if not p.name.endswith(("-mono.pdf", "-dual.pdf", "-zh.pdf"))]
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print("没找到要翻译的 PDF。")
        return 1

    print(f"共 {len(pdfs)} 篇，引擎={env.get('engine')} 模型={env.get('OPENAI_MODEL')}")
    print(f"参考文献保持原文: {'否' if keep_refs else '是'}")
    print(f"输出目录: {outdir}\n")

    ok, fail, skipped = [], [], []
    for i, pdf in enumerate(pdfs, 1):
        stem = pdf.stem
        if args.resume and ((outdir / f"{stem}-mono.pdf").exists()
                            or (outdir / f"{stem}-dual.pdf").exists()):
            skipped.append(pdf.name)
            print(f"[{i}/{len(pdfs)}] 跳过（已有成果）: {pdf.name}")
            continue

        print(f"[{i}/{len(pdfs)}] 翻译中: {pdf.name} ...", flush=True)
        code, log, dt = translate_one(pdf, env, prompt_file, outdir,
                                      args.threads or int(env.get("threads", 4)),
                                      args.fresh, keep_refs)
        (LOG_DIR / f"{stem}.log").write_text(log, encoding="utf-8")
        if code == 0:
            ok.append((pdf.name, dt))
            print(f"    完成，用时 {dt:.1f}s")
        else:
            fail.append((pdf.name, code))
            print(f"    失败 code={code}，日志见 logs/{stem}.log")
            tail = "\n".join(log.strip().splitlines()[-12:])
            print("    " + tail.replace("\n", "\n    "))

    print("\n========== 汇总 ==========")
    print(f"成功 {len(ok)} 篇 / 跳过 {len(skipped)} 篇 / 失败 {len(fail)} 篇")
    for n, dt in ok:
        print(f"  OK   {n}  ({dt:.1f}s)")
    for n, c in fail:
        print(f"  FAIL {n}  (code={c})")
    (LOG_DIR / "汇总.json").write_text(
        json.dumps({"ok": [n for n, _ in ok], "fail": fail, "skipped": skipped},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not fail else 2


if __name__ == "__main__":
    sys.exit(main())
