"""Query rewriting for RAG recall (multi-query / keyword expansion pattern).

Industry pattern (Azure AI Search, Elasticsearch RRF stacks):
  L0 query rewrite -> L1 parallel recall -> RRF fusion -> L2 rerank

This module is rule-based (no extra LLM call) for stable latency.
"""

from __future__ import annotations

import re
from typing import Any

from ly_next.rag.retrieval_fusion import tokenize

_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "about",
        "what",
        "how",
        "why",
        "when",
        "where",
        "which",
        "who",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "not",
        "no",
        "yes",
        "的",
        "了",
        "是",
        "在",
        "有",
        "和",
        "与",
        "或",
        "及",
        "等",
        "我",
        "你",
        "他",
        "她",
        "它",
        "我们",
        "你们",
        "他们",
        "什么",
        "怎么",
        "如何",
        "为什么",
        "哪里",
        "哪个",
        "哪些",
        "请",
        "帮",
        "一下",
        "吗",
        "呢",
        "吧",
        "啊",
    }
)

_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}")


def _rewrite_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return cfg if isinstance(cfg, dict) else {}


def rewrite_enabled(cfg: dict[str, Any] | None = None) -> bool:
    c = _rewrite_cfg(cfg)
    return bool(c.get("enabled", True))


def extract_keywords(query: str) -> list[str]:
    tokens = tokenize(query)
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t in _STOP or len(t) < 2:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def extract_identifiers(query: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _IDENTIFIER_RE.finditer(query or ""):
        t = m.group(0).strip()
        low = t.lower()
        if low in _STOP or low in seen:
            continue
        seen.add(low)
        found.append(t)
    return found


def expand_queries(
    query: str,
    *,
    max_variants: int = 4,
    include_keywords: bool = True,
    include_identifiers: bool = True,
) -> list[str]:
    """Return deduplicated query variants for multi-query recall."""
    q = (query or "").strip()
    if not q:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        c = " ".join(candidate.strip().split())
        if not c:
            return
        key = c.lower()
        if key in seen:
            return
        seen.add(key)
        variants.append(c)

    _add(q)

    keywords = extract_keywords(q) if include_keywords else []
    if keywords:
        _add(" ".join(keywords[:12]))

    identifiers = extract_identifiers(q) if include_identifiers else []
    for ident in identifiers[:6]:
        _add(ident)

    if len(keywords) >= 2:
        _add(" ".join(keywords[:4]))

    return variants[: max(1, max_variants)]


def should_expand_weak_recall(
    top_score: float,
    *,
    threshold: float,
    adaptive: bool,
) -> bool:
    if not adaptive:
        return True
    return float(top_score) < float(threshold)
