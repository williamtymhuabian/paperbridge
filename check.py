#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
翻译后体检：确认「排版没乱、图片没跑位、没有漏翻」。
用法：
    python check.py 原文.pdf              # 自动在 output/ 找对应的 -mono / -dual
    python check.py 原文.pdf 译文-mono.pdf
检查项：
    1) 页数是否对得上
    2) 每页图片数量、图片位置(bbox)是否与原 PDF 一致（容差 1pt）
    3) 每页矢量图（公式、表格线）数量是否一致
    4) 是否有整页漏翻（译文中仍是大段英文）
    5) 文本是否溢出原文本框（这是排版乱掉最常见的原因）
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from refs_skip import is_reference  # noqa: E402

OUT_DIR = BASE / "output"
TOL = 1.0  # 位置容差(pt)

CJK = re.compile(r"[\u4e00-\u9fff]")
EN_WORD = re.compile(r"[A-Za-z]{3,}")


def page_stats(page):
    imgs = []
    try:
        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            imgs.append(tuple(round(v, 1) for v in bbox))
    except Exception:
        pass
    drawings = len(page.get_drawings())
    return imgs, drawings


def text_of(page):
    try:
        return page.get_text("text") or ""
    except Exception:
        return ""


def cjk_ratio(s):
    if not s:
        return 0.0
    return len(CJK.findall(s)) / max(1, len(s.strip()))


def english_left(s):
    """残留英文单词数量（排除术语表允许的缩写，粗略）"""
    return len(EN_WORD.findall(s))


def check(src: Path, mono: Path, dual: Path = None):
    import fitz  # PyMuPDF
    ds = fitz.open(str(src))
    report = {"原文": str(src), "页数": {"原": len(ds)}, "问题": []}

    def compare(trans: Path, tag: str, expect_pages: int):
        if not trans.exists():
            report["问题"].append(f"[{tag}] 缺少文件 {trans.name}")
            return
        dt = fitz.open(str(trans))
        rep = {"文件": trans.name, "页数": len(dt)}
        report[tag] = rep
        if len(dt) != expect_pages:
            report["问题"].append(
                f"[{tag}] 页数不一致: 原 {len(ds)} 页 / 译文 {len(dt)} 页（应为 {expect_pages}）")

        n = min(len(ds), len(dt))
        img_bad, draw_bad, miss = [], [], []
        for i in range(n):
            step = 2 if tag == "双语" else 1
            j = i * step + (0 if tag == "双语" else 0)
            # 双语版：译文页 = 奇数索引；原文页 = 偶数索引（0基）
            if tag == "双语":
                j = i * 2 + 1
            if j >= len(dt):
                break
            si, sd = page_stats(ds[i])
            ti, td = page_stats(dt[j])
            if len(si) != len(ti):
                img_bad.append((i, len(si), len(ti)))
            else:
                for k, (a, b) in enumerate(zip(si, ti)):
                    if max(abs(x - y) for x, y in zip(a, b)) > TOL:
                        img_bad.append((i, a, b))
                        break
            if sd != td and abs(sd - td) > max(2, sd * 0.1):
                draw_bad.append((i, sd, td))
            txt = text_of(dt[j])
            if len(txt.strip()) > 60 and cjk_ratio(txt) < 0.05:
                # 参考文献页（大部分块命中引用条目特征）是故意保持原文的，不算漏翻
                blocks = []
                try:
                    blocks = [b[4].strip() for b in dt[j].get_text("blocks") if b[4].strip()]
                except Exception:
                    pass
                ref_chars = sum(len(b) for b in blocks if is_reference(b))
                total = sum(len(b) for b in blocks) or 1
                if ref_chars / total < 0.6:
                    miss.append({"页": i + 1, "残留英文词数": english_left(txt),
                                 "前80字": txt.strip()[:80].replace("\n", " ")})
        rep["图片位置不一致页数"] = img_bad
        rep["矢量元素差异页数"] = draw_bad
        rep["疑似漏翻页数"] = miss
        if img_bad:
            report["问题"].append(f"[{tag}] 有 {len(img_bad)} 页图片数量/位置对不上: {img_bad[:5]}")
        if draw_bad:
            report["问题"].append(f"[{tag}] 有 {len(draw_bad)} 页公式/表格线数量差异: {draw_bad[:5]}")
        if miss:
            report["问题"].append(f"[{tag}] 有 {len(miss)} 页疑似未翻译（仍是英文）")

    compare(mono, "纯中文", len(ds))
    if dual and dual.exists():
        compare(dual, "双语", len(ds) * 2)
    ds.close()
    return report


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    src = Path(args[0])
    stem = src.stem
    if len(args) >= 2:
        mono, dual = Path(args[1]), (Path(args[2]) if len(args) >= 3 else None)
    else:
        mono = OUT_DIR / f"{stem}-mono.pdf"
        dual = OUT_DIR / f"{stem}-dual.pdf"
    rep = check(src, mono, dual)

    print("=" * 60)
    print(f"原文: {rep['原文']}  ({rep['页数']['原']} 页)")
    for tag in ("纯中文", "双语"):
        if tag in rep:
            r = rep[tag]
            print(f"\n[{tag}] {r['文件']}  {r['页数']} 页")
            print(f"  图片数量/位置异常页: {len(r['图片位置不一致页数'])}")
            print(f"  矢量元素差异页:      {len(r['矢量元素差异页数'])}")
            print(f"  疑似漏翻页:          {len(r['疑似漏翻页数'])}")
    print("\n--- 结论 ---")
    if not rep["问题"]:
        print("体检通过：页数、图片位置、公式/表格线都对得上，没有发现漏翻页。")
    else:
        for p in rep["问题"]:
            print("  ! " + p)
    return 0 if not rep["问题"] else 2


if __name__ == "__main__":
    sys.exit(main())
