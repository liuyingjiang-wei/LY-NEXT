from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def bm25_rank(
    query: str,
    documents: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[float, str]]:
    if not documents:
        return []
    q_terms = tokenize(query)
    if not q_terms:
        return [(0.0, d) for d in documents]

    tokenized = [tokenize(d) for d in documents]
    n_docs = len(documents)
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))

    dl_list = [max(len(toks), 1) for toks in tokenized]
    avgdl = sum(dl_list) / max(n_docs, 1)

    idf: dict[str, float] = {}
    for t in set(q_terms):
        n = df.get(t, 0)
        idf[t] = math.log((n_docs - n + 0.5) / (n + 0.5) + 1.0)

    scored: list[tuple[float, str]] = []
    for toks, doc in zip(tokenized, documents, strict=False):
        dl = max(len(toks), 1)
        tf = Counter(toks)
        s = 0.0
        for t in q_terms:
            f = int(tf.get(t, 0))
            if f == 0:
                continue
            idf_t = idf.get(t, 0.0)
            denom = f + k1 * (1.0 - b + b * (dl / max(avgdl, 1e-6)))
            s += idf_t * (f * (k1 + 1.0)) / denom
        scored.append((s, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def rrf_fuse(rank_lists: list[list[tuple[float, str]]], *, k: int = 60) -> list[tuple[float, str]]:
    if not rank_lists:
        return []
    scores: dict[str, float] = {}
    for lst in rank_lists:
        for rank, (_sc, chunk) in enumerate(lst, start=1):
            if not chunk:
                continue
            scores[chunk] = scores.get(chunk, 0.0) + 1.0 / (k + rank)
    out = [(s, ch) for ch, s in scores.items()]
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def mmr_select_vectors(
    ranked: list[tuple[float, str]],
    *,
    chunks: list[str],
    vectors: list[list[float]],
    query_vec: list[float],
    top_k: int,
    pool_size: int,
    lambda_param: float,
    cosine_fn: Any,
) -> list[tuple[float, str]]:
    """MMR: λ·sim(d,q) − (1−λ)·max_{s∈S} sim(d,s)."""
    if top_k <= 0 or not ranked or not query_vec:
        return ranked[:top_k]

    lam = max(0.0, min(1.0, float(lambda_param)))
    idx_map: dict[str, int] = {}
    for i, c in enumerate(chunks):
        if c not in idx_map:
            idx_map[c] = i

    rrf_score: dict[str, float] = {ch: sc for sc, ch in ranked}
    pool: list[str] = []
    seen: set[str] = set()
    for _sc, ch in ranked:
        if not ch or ch in seen:
            continue
        j = idx_map.get(ch)
        if j is None or j >= len(vectors):
            continue
        seen.add(ch)
        pool.append(ch)
        if len(pool) >= pool_size:
            break

    selected: list[str] = []
    while len(selected) < top_k and pool:
        best_ch: str | None = None
        best_mmr = -1e9
        for ch in pool:
            j = idx_map[ch]
            rel = cosine_fn(query_vec, vectors[j])
            if selected:
                sims_to_sel = [
                    cosine_fn(vectors[j], vectors[idx_map[s]])
                    for s in selected
                    if s in idx_map and idx_map[s] < len(vectors)
                ]
                mx = max(sims_to_sel) if sims_to_sel else 0.0
                mmr = lam * rel - (1.0 - lam) * mx
            else:
                mmr = rel
            if mmr > best_mmr:
                best_mmr = mmr
                best_ch = ch
        if not best_ch:
            break
        selected.append(best_ch)
        pool = [c for c in pool if c != best_ch]

    return [(rrf_score.get(ch, 0.0), ch) for ch in selected]
