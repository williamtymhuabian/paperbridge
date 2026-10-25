# -*- coding: utf-8 -*-
"""
参考文献保持原文（块级判定）。
页面级切分由 translate.py 负责（预扫描 References 起始页，分片翻译后拼接），
本模块只负责"References 标题所在混合页"上的条目级判定：
命中引用条目特征的文本块直接返回原文，不送翻译引擎。

设计取向：宁可漏掉个别条目不跳过，也绝不把正文误判成引用。
"""
import re

CJK = re.compile(r"[\u4e00-\u9fff]")
RE_START = re.compile(r"^\s*[\[\(]\d+\]")
RE_ETAL = re.compile(r"et al\.?")
RE_VENUE = re.compile(
    r"(Proceedings|Conference on|Journal of|Transactions on|Advances in Neural"
    r"|In Proc\.|Proc\. of|CVPR|ICCV|ECCV|ICML|ICLR|NeurIPS"
    r"|ICRA|IROS|CoRL|AAAI|IJCAI|ACL|EMNLP|Interspeech|IEEE|ACM|Springer|Elsevier"
    r"|Scientific Reports|Nature\b|Science\b|JASA|PMLR)", re.I)
RE_META = re.compile(r"(vol\.|no\.|pp\.|doi\.org|DOI:|ISBN|Technical Report)", re.I)
RE_YEAR = re.compile(r"(?:19|20)\d{2}")
RE_ENDYEAR = re.compile(r"(?:19|20)\d{2}[\s\.\)\,]*$")
RE_AUTHOR_APA = re.compile(r"\b[A-Z][a-zà-ÿ\-]+,\s*[A-Z]\.")      # Smith, J.
RE_AUTHOR_INIT = re.compile(r"\b[A-Z]\.\s*[A-Z][a-zà-ÿ\-]+")       # J. Smith
RE_ARXIV_END = re.compile(r"arXiv[:\s]*\d{4}\.\d{4,5}[\s\.]*$", re.I)
RE_URL = re.compile(r"^https?://|doi\.org/", re.I)
# 条目开头（行首）：编号制 / APA 作者 / 首字母作者
RE_ENTRY_START = re.compile(
    r"(?m)^\s*(?:\[\d+\]|\(\d+\)|[A-Z][a-zà-ÿ\-]+,\s*[A-Z]\.|[A-Z]\.\s*[A-Z][a-zà-ÿ\-]+)")


def _score_entry(t: str):
    """返回 (score, strong)"""
    n_author_apa = len(RE_AUTHOR_APA.findall(t))
    n_author_init = len(RE_AUTHOR_INIT.findall(t))
    has_start = bool(RE_START.match(t))
    has_arxiv = bool(RE_ARXIV_END.search(t))
    has_venue = bool(RE_VENUE.search(t))
    has_endyear = bool(RE_ENDYEAR.search(t))
    n_years = len(RE_YEAR.findall(t))

    score = 0
    if has_start:                       score += 2
    if n_author_apa >= 2:               score += 3
    if n_author_init >= 2:              score += 3
    if has_arxiv:                       score += 2
    if has_venue:                       score += 2
    if n_years >= 2:                    score += 2
    if has_endyear:                     score += 1
    if RE_META.search(t):               score += 1
    if RE_ETAL.search(t):               score += 1

    strong = (has_start or n_author_apa >= 2 or n_author_init >= 2
              or (has_arxiv and bool(RE_ETAL.search(t) or n_author_init or n_author_apa))
              or (has_venue and (has_endyear or n_years >= 1)))
    return score, strong


def is_reference(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if CJK.search(t):          # 已含中文的块不处理
        return False
    if t.lower().rstrip(":") in ("references", "bibliography", "literature cited"):
        return True            # 节标题保持原文，与未翻条目保持一致
    if RE_URL.match(t):        # 纯链接行
        return True
    # 长块（pdf2zh 常把整栏条目聚成一个大 patch，且段内无换行）：
    # 数“姓, 名缩写.”模式的全局出现次数，≥4 即判为参考文献块。
    # 正文段落极少出现 4 个以上这种模式（文内引用一般是 (Lee & Lee, 2025) 格式）。
    if len(t) > 800:
        return (len(RE_AUTHOR_APA.findall(t)) + len(RE_ENTRY_START.findall(t))) >= 4

    score, strong = _score_entry(t)
    return score >= 3 if strong else score >= 6


def patch():
    """给 pdf2zh 所有翻译引擎打补丁。
    必须包在 BaseTranslator.translate（统一入口）上：
    各引擎子类都自定义了 do_translate，patch 它会被子类覆盖。"""
    import os
    from pdf2zh.translator import BaseTranslator
    if getattr(BaseTranslator, "_refs_skip_patched", False):
        return
    orig = BaseTranslator.translate
    dbg = os.environ.get("REFS_DEBUG")

    def translate(self, text: str, ignore_cache: bool = False) -> str:
        t = (text or "").strip()
        skip = bool(t) and is_reference(t)
        if dbg and t:
            try:
                with open(dbg, "a", encoding="utf-8") as f:
                    f.write(f"LEN={len(t)} APA={len(RE_AUTHOR_APA.findall(t))} "
                            f"START={len(RE_ENTRY_START.findall(t))} SKIP={skip} "
                            f"NEWLINES={t.count(chr(10))} | {t[:80]!r}\n")
            except OSError:
                pass
        if skip:
            return text
        return orig(self, text, ignore_cache)

    BaseTranslator.translate = translate
    BaseTranslator._refs_skip_patched = True
