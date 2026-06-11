from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_data_root, get_project_root
from ly_next.core.database import RAG_EMBEDDING_DIM, db
from ly_next.core.logger import get_logger
from ly_next.rag.chunk_document import chunk_document
from ly_next.rag.embedding_config import resolve_embedding_http_config
from ly_next.rag.embeddings import fetch_embeddings
from ly_next.rag.query_rewrite import expand_queries, rewrite_enabled, should_expand_weak_recall
from ly_next.rag.reranker import rerank_chunks
from ly_next.rag.retrieval_fusion import bm25_rank, mmr_select_vectors, rrf_fuse
from ly_next.rag.similarity import cosine_similarity, jaccard_similarity

logger = get_logger(__name__)

_DOC_SUFFIXES = frozenset({".md", ".txt", ".markdown"})
_QUERY_RESULT_CACHE: dict[str, tuple[float, list[tuple[float, str, str]]]] = {}
_QUERY_CACHE_MAX = 128


def _resolve_documents_path(raw: str) -> Path:
    """Resolve RAG corpus path; tolerate ``data/ly_next/...`` when config dir is customized."""
    s = (raw or "").strip()
    if not s:
        return Path()
    p = Path(s)
    if p.is_absolute():
        return p
    root = get_project_root()
    candidates: list[Path] = [root / p]
    dr = get_data_root()
    parts = p.parts
    if len(parts) >= 2 and parts[0] == "data" and parts[1] == "ly_next":
        candidates.append(dr / Path(*parts[2:]))
    if p.name == "knowledge":
        candidates.append(dr / "knowledge")
    seen: set[Path] = set()
    for target in candidates:
        key = target.resolve()
        if key in seen:
            continue
        seen.add(key)
        if target.exists():
            return target
    return candidates[0]


def _list_corpus_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() in _DOC_SUFFIXES else []
    if not target.is_dir():
        return []
    return sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in _DOC_SUFFIXES)


def _build_index_config_sig() -> str:
    h = hashlib.sha256()
    for key in ("chunk_size", "chunk_overlap", "chunk_strategy", "contextual_chunks"):
        h.update(f"{key}={config.get(f'agent.rag.{key}', '')}".encode())
    return h.hexdigest()[:16]


def _build_corpus_sig(target: Path) -> str:
    h = hashlib.sha256()
    for p in _list_corpus_files(target):
        try:
            st = p.stat()
            rel = str(p)
            h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8", errors="ignore"))
        except OSError:
            h.update(str(p).encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _query_cache_key(query: str, top_k: int, corpus_sig: str) -> str:
    norm = " ".join((query or "").strip().lower().split())
    digest = hashlib.sha256(f"{norm}|{top_k}|{corpus_sig}".encode()).hexdigest()[:40]
    return digest


def _query_cache_get(key: str, ttl_seconds: float) -> list[tuple[float, str, str]] | None:
    row = _QUERY_RESULT_CACHE.get(key)
    if row is None:
        return None
    ts, value = row
    if time.monotonic() - ts > ttl_seconds:
        _QUERY_RESULT_CACHE.pop(key, None)
        return None
    return value


def _query_cache_put(key: str, value: list[tuple[float, str, str]]) -> None:
    if len(_QUERY_RESULT_CACHE) >= _QUERY_CACHE_MAX:
        oldest = min(_QUERY_RESULT_CACHE.items(), key=lambda item: item[1][0])[0]
        _QUERY_RESULT_CACHE.pop(oldest, None)
    _QUERY_RESULT_CACHE[key] = (time.monotonic(), value)


class DocumentRetriever:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._embed_texts: list[str] = []
        self._sources: list[str] = []
        self._vectors: list[list[float]] | None = None
        self._loaded_path = ""
        self._corpus_sig = ""
        self._index_config_sig = ""
        self._pg_store_sig = ""
        self._pg_store_disabled = False
        self._warned_empty_path = False
        self._configured_once = False

    def configure(self) -> None:
        raw = str(config.get("agent.rag.documents_path", "") or "").strip()
        if not raw:
            self._chunks = []
            self._embed_texts = []
            self._sources = []
            self._vectors = None
            self._loaded_path = raw
            self._corpus_sig = ""
            self._index_config_sig = ""
            self._configured_once = True
            self._pg_store_sig = ""
            self._pg_store_disabled = False
            if bool(config.get("agent.rag.enabled", False)) and not self._warned_empty_path:
                self._warned_empty_path = True
                logger.warning(
                    "[rag.docs] agent.rag.documents_path is empty; document retrieval is disabled."
                )
            return
        self._warned_empty_path = False

        target = _resolve_documents_path(raw)
        new_sig = _build_corpus_sig(target)
        new_index_sig = _build_index_config_sig()
        if (
            self._configured_once
            and self._loaded_path == raw
            and new_sig == self._corpus_sig
            and new_index_sig == self._index_config_sig
            and self._chunks
        ):
            return

        self._chunks = []
        self._embed_texts = []
        self._sources = []
        self._vectors = None
        self._loaded_path = raw
        self._corpus_sig = new_sig
        self._index_config_sig = new_index_sig
        self._configured_once = True
        self._pg_store_sig = ""
        self._pg_store_disabled = False
        contextual = bool(config.get("agent.rag.contextual_chunks", True))

        file_units: list[tuple[str, str]] = []
        if target.is_file():
            file_units.append((target.name, _read_file(target)))
        elif target.is_dir():
            for p in _list_corpus_files(target):
                try:
                    rel = str(p.relative_to(target))
                except ValueError:
                    rel = p.name
                file_units.append((rel, _read_file(p)))
        else:
            logger.warning("[rag.docs] Path not found: %s", target)

        chunk_size = int(config.get("agent.rag.chunk_size", 512) or 512)
        overlap = int(config.get("agent.rag.chunk_overlap", 64) or 64)
        chunk_strategy = str(config.get("agent.rag.chunk_strategy", "markdown") or "markdown")
        for src_label, t in file_units:
            for c in chunk_document(
                t, strategy=chunk_strategy, chunk_size=chunk_size, overlap=overlap
            ):
                if c:
                    self._chunks.append(c)
                    self._sources.append(src_label)
                    if contextual and src_label:
                        self._embed_texts.append(f"[{src_label}]\n{c}")
                    else:
                        self._embed_texts.append(c)

    async def retrieve_formatted(self, user_query: str, *, top_k: int | None = None) -> str:
        if not config.get("agent.rag.enabled", False):
            return ""
        path_cfg = str(config.get("agent.rag.documents_path", "") or "").strip()
        if not self._configured_once or self._loaded_path != path_cfg:
            self.configure()
        if not self._chunks or not user_query.strip():
            return ""

        show_src = bool(config.get("agent.rag.show_source", True))
        picked = await self._pick_for_query(user_query, top_k=top_k)
        if not picked:
            return ""

        parts = []
        for i, (score, ch, src) in enumerate(picked, 1):
            head = f"片段{i}（相关度 {score:.3f}）"
            if show_src and src:
                head += f" · 来源 {src}"
            parts.append(f"{head}\n{ch}")
        return "\n\n---\n\n".join(parts)

    async def retrieve_results(
        self, user_query: str, *, top_k: int | None = None
    ) -> dict[str, Any]:
        """Structured hits for workbench RAG trial retrieval."""
        enabled = bool(config.get("agent.rag.enabled", False))
        path_cfg = str(config.get("agent.rag.documents_path", "") or "").strip()
        if not enabled:
            return {
                "enabled": False,
                "documents_path": path_cfg,
                "chunks_loaded": 0,
                "hits": [],
                "hint": "agent.rag.enabled 为 false",
            }
        if not self._configured_once or self._loaded_path != path_cfg:
            self.configure()
        q = user_query.strip()
        if not q:
            return {
                "enabled": True,
                "documents_path": self._loaded_path,
                "chunks_loaded": len(self._chunks),
                "hits": [],
                "hint": "请输入检索问题",
            }
        if not self._chunks:
            return {
                "enabled": True,
                "documents_path": self._loaded_path,
                "chunks_loaded": 0,
                "hits": [],
                "hint": "知识库为空或路径无效，请检查 documents_path",
            }
        picked = await self._pick_for_query(q, top_k=top_k)
        hits = [
            {
                "rank": i,
                "score": round(float(score), 4),
                "source": src or "",
                "text": ch,
                "preview": ch[:320] + ("…" if len(ch) > 320 else ""),
            }
            for i, (score, ch, src) in enumerate(picked, 1)
        ]
        return {
            "enabled": True,
            "documents_path": self._loaded_path,
            "chunks_loaded": len(self._chunks),
            "hits": hits,
            "hint": None if hits else "未命中片段，可调低 min_similarity 或检查文档内容",
        }

    def _source_for_chunk(self, ch: str) -> str:
        if not self._sources or not self._chunks:
            return ""
        try:
            ix = self._chunks.index(ch)
            if 0 <= ix < len(self._sources):
                return self._sources[ix]
        except ValueError:
            pass
        return ""

    async def _pick_for_query(
        self, user_query: str, *, top_k: int | None = None
    ) -> list[tuple[float, str, str]]:
        effective_top_k = int(top_k if top_k is not None else config.get("agent.rag.top_k", 5) or 5)
        effective_top_k = max(1, effective_top_k)
        cache_ttl = float(config.get("agent.rag.query_cache_ttl_seconds", 90) or 0)
        if cache_ttl > 0:
            cache_key = _query_cache_key(user_query, effective_top_k, self._corpus_sig)
            cached = _query_cache_get(cache_key, cache_ttl)
            if cached is not None:
                return cached

        timeout = float(config.get("agent.rag.retrieval_timeout_seconds", 45) or 0)
        try:
            if timeout > 0:
                picked = await asyncio.wait_for(
                    self._pick_for_query_impl(user_query, top_k=effective_top_k),
                    timeout=timeout,
                )
            else:
                picked = await self._pick_for_query_impl(user_query, top_k=effective_top_k)
        except TimeoutError:
            logger.warning("[rag.docs] Retrieval timed out after %.1fs", timeout)
            picked = self._lexical_fallback_picks(user_query, top_k=effective_top_k)

        if cache_ttl > 0 and picked:
            _query_cache_put(cache_key, picked)
        return picked

    def _lexical_fallback_picks(
        self, user_query: str, *, top_k: int
    ) -> list[tuple[float, str, str]]:
        ranked = self._rank_lexical(user_query)[:top_k]
        return [(float(s), ch, self._source_for_chunk(ch)) for s, ch in ranked]

    def _rewrite_cfg(self) -> dict[str, Any]:
        raw = config.get("agent.rag.query_rewrite", {}) or {}
        return raw if isinstance(raw, dict) else {}

    def _recall_queries(self, user_query: str, *, expand: bool) -> list[str]:
        if not expand or not rewrite_enabled(self._rewrite_cfg()):
            return [user_query]
        cfg = self._rewrite_cfg()
        max_variants = max(1, int(cfg.get("max_variants", 4) or 4))
        return expand_queries(
            user_query,
            max_variants=max_variants,
            include_keywords=bool(cfg.get("include_keywords", True)),
            include_identifiers=bool(cfg.get("include_identifiers", True)),
        )

    async def _l1_hybrid_recall(
        self,
        user_query: str,
        *,
        pool_n: int,
        use_emb: bool,
        hybrid: bool,
        rrf_k: int,
        expand: bool,
    ) -> tuple[list[tuple[float, str]], list[float] | None]:
        """L1 recall: parallel dense + BM25 lists, fused with RRF (k=60 default)."""
        rank_lists: list[list[tuple[float, str]]] = []
        q_vec: list[float] | None = None

        if use_emb:
            try:
                queries = self._recall_queries(user_query, expand=expand)
                for q in queries:
                    dense_ranked, qv = await self._rank_embedding_with_query_vec(q)
                    if qv is not None and q_vec is None:
                        q_vec = qv
                    if dense_ranked:
                        rank_lists.append(dense_ranked[:pool_n])
            except Exception as e:
                logger.warning(
                    "[rag.docs] Embedding retrieve failed, fallback lexical (%s): %s",
                    type(e).__name__,
                    str(e).strip() or repr(e),
                )
                rank_lists.append(self._rank_lexical(user_query)[:pool_n])
        else:
            rank_lists.append(self._rank_lexical(user_query)[:pool_n])

        if hybrid and self._chunks:
            bm25_ranked = bm25_rank(user_query, self._chunks)[:pool_n]
            rank_lists.append(bm25_ranked)
            if use_emb:
                lex_jac = self._rank_lexical(user_query)[:pool_n]
                rank_lists.append(lex_jac)

        if not rank_lists:
            return ([], q_vec)
        if len(rank_lists) == 1:
            return (rank_lists[0], q_vec)
        return (rrf_fuse(rank_lists, k=rrf_k), q_vec)

    async def _pick_for_query_impl(
        self, user_query: str, *, top_k: int
    ) -> list[tuple[float, str, str]]:
        min_sim = float(config.get("agent.rag.min_similarity", 0.20) or 0.0)
        use_emb = bool(config.get("agent.rag.use_embeddings", True))
        hybrid = bool(config.get("agent.rag.hybrid_enabled", True))
        rrf_k = int(config.get("agent.rag.rrf_k", 60) or 60)
        mmr_on = bool(config.get("agent.rag.mmr_enabled", True))
        mmr_lambda = float(config.get("agent.rag.mmr_lambda", 0.6) or 0.6)
        mult = max(1, int(config.get("agent.rag.retrieve_multiplier", 5) or 5))
        rerank_cfg = config.get("agent.rag.rerank", {}) or {}
        if not isinstance(rerank_cfg, dict):
            rerank_cfg = {}
        rerank_on = bool(rerank_cfg.get("enabled", False))
        rerank_top_n = max(top_k, int(rerank_cfg.get("top_n", top_k * mult) or top_k * mult))
        pool_n = max(top_k * mult, rerank_top_n if rerank_on else top_k * mult)

        rewrite_cfg = self._rewrite_cfg()
        adaptive = bool(rewrite_cfg.get("adaptive", True))
        weak_threshold = float(rewrite_cfg.get("weak_score_threshold", 0.35) or 0.35)

        ranked, q_vec = await self._l1_hybrid_recall(
            user_query,
            pool_n=pool_n,
            use_emb=use_emb,
            hybrid=hybrid,
            rrf_k=rrf_k,
            expand=False,
        )
        if ranked and should_expand_weak_recall(
            ranked[0][0],
            threshold=weak_threshold,
            adaptive=adaptive,
        ):
            expanded_ranked, expanded_qv = await self._l1_hybrid_recall(
                user_query,
                pool_n=pool_n,
                use_emb=use_emb,
                hybrid=hybrid,
                rrf_k=rrf_k,
                expand=True,
            )
            if expanded_ranked:
                ranked = rrf_fuse([ranked, expanded_ranked], k=rrf_k)
                if expanded_qv is not None:
                    q_vec = expanded_qv

        pool = ranked[:pool_n] if ranked else []

        if mmr_on and q_vec and self._vectors and len(self._vectors) == len(self._chunks) and pool:
            pool = mmr_select_vectors(
                pool,
                chunks=self._chunks,
                vectors=self._vectors,
                query_vec=q_vec,
                top_k=min(len(pool), pool_n),
                pool_size=pool_n,
                lambda_param=mmr_lambda,
                cosine_fn=cosine_similarity,
            )

        if rerank_on and pool:
            picked = await rerank_chunks(user_query, pool, top_k=top_k)
        else:
            picked = pool[:top_k]

        if not rerank_on:
            filtered = [(s, ch) for s, ch in picked if s >= min_sim][:top_k]
            if filtered:
                picked = filtered
            elif picked and picked[0][0] > 0:
                picked = picked[:1]

        return [(float(s), ch, self._source_for_chunk(ch)) for s, ch in picked[:top_k]]

    def _rank_lexical(self, user_query: str) -> list[tuple[float, str]]:
        ranked: list[tuple[float, str]] = []
        for ch in self._chunks:
            ranked.append((jaccard_similarity(user_query, ch), ch))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    async def _rank_embedding(self, user_query: str) -> list[tuple[float, str]]:
        ranked, _qv = await self._rank_embedding_with_query_vec(user_query)
        return ranked

    async def _rank_embedding_with_query_vec(
        self, user_query: str
    ) -> tuple[list[tuple[float, str]], list[float] | None]:
        emb_cfg = config.get("agent.rag.embedding", {}) or {}
        if not isinstance(emb_cfg, dict):
            emb_cfg = {}
        hp = resolve_embedding_http_config(emb_cfg, config.get)
        model = hp["model"]
        api_key = hp["api_key"]
        base_url = hp["base_url"]
        timeout = hp["timeout"]
        auth_mode = hp["auth_mode"]
        auth_header_name = hp["auth_header_name"]
        extra_h = hp["extra_headers"]
        task_q = hp.get("task_query")
        task_p = hp.get("task_passage")
        dims = hp.get("dimensions")
        dim_opt: int | None = None
        if dims is not None:
            try:
                di = int(dims)
                dim_opt = di if di > 0 else None
            except (TypeError, ValueError):
                dim_opt = None
        xbody = hp.get("extra_body") if isinstance(hp.get("extra_body"), dict) else None

        embed_inputs = self._embed_texts or self._chunks
        if self._vectors is None or len(self._vectors) != len(embed_inputs):
            batch = 32
            all_vec: list[list[float]] = []
            for i in range(0, len(embed_inputs), batch):
                sub = embed_inputs[i : i + batch]
                part = await fetch_embeddings(
                    sub,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    auth_mode=auth_mode,
                    auth_header_name=auth_header_name,
                    extra_headers=extra_h,
                    task=str(task_p) if task_p else None,
                    dimensions=dim_opt,
                    extra_body=xbody,
                )
                all_vec.extend(part)
            self._vectors = all_vec

        await self._ensure_pgvector_store()

        q_vecs = await fetch_embeddings(
            [user_query],
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            auth_mode=auth_mode,
            auth_header_name=auth_header_name,
            extra_headers=extra_h,
            task=str(task_q) if task_q else None,
            dimensions=dim_opt,
            extra_body=xbody,
        )
        if not q_vecs:
            return (self._rank_lexical(user_query), None)
        qv = q_vecs[0]

        ranked_pg = await self._query_pgvector(qv)
        if ranked_pg:
            return (ranked_pg, qv)

        ranked: list[tuple[float, str]] = []
        for ch, vec in zip(self._chunks, self._vectors or [], strict=False):
            ranked.append((cosine_similarity(qv, vec), ch))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return (ranked, qv)

    def _build_chunk_store_sig(self) -> str:
        h = hashlib.sha256()
        h.update(self._corpus_sig.encode("utf-8"))
        h.update(str(len(self._chunks)).encode("utf-8"))
        vlen = len(self._vectors or [])
        h.update(str(vlen).encode("utf-8"))
        if self._vectors:
            h.update(str(len(self._vectors[0])).encode("utf-8"))
        return h.hexdigest()

    async def _ensure_pgvector_store(self) -> None:
        if self._pg_store_disabled or not self._chunks or not self._vectors:
            return
        sig = self._build_chunk_store_sig()
        if sig == self._pg_store_sig:
            return
        if db._engine is None:
            try:
                await db.connect()
            except Exception as e:
                logger.warning("[rag.docs] DB unavailable, using in-memory vectors: %s", e)
                self._pg_store_disabled = True
                return

        bad = next(
            (
                i
                for i, v in enumerate(self._vectors)
                if not isinstance(v, list) or len(v) != RAG_EMBEDDING_DIM
            ),
            None,
        )
        if bad is not None:
            logger.warning(
                "[rag.docs] Embedding dim != %s (chunk index %s); using in-memory vectors.",
                RAG_EMBEDDING_DIM,
                bad,
            )
            self._pg_store_disabled = True
            return

        rows: list[tuple[str, int, str, list[float]]] = []
        for i, (src, ch, vec) in enumerate(
            zip(self._sources, self._chunks, self._vectors or [], strict=False)
        ):
            if isinstance(vec, list) and vec:
                rows.append((src, i, ch, vec))

        if not rows:
            return

        try:
            await db.replace_rag_chunks(rows)
            self._pg_store_sig = sig
            logger.info("[rag.docs] pgvector store refreshed (%s rows)", len(rows))
        except Exception as e:
            logger.warning("[rag.docs] pgvector write failed, using in-memory vectors: %s", e)
            self._pg_store_disabled = True

    async def _query_pgvector(self, query_vec: list[float]) -> list[tuple[float, str]]:
        if not query_vec or self._pg_store_disabled:
            return []
        if len(query_vec) != RAG_EMBEDDING_DIM:
            return []
        if not self._pg_store_sig:
            return []
        if db._engine is None:
            return []

        top_k = int(config.get("agent.rag.top_k", 5) or 5)
        mult = max(1, int(config.get("agent.rag.retrieve_multiplier", 5) or 5))
        limit = max(1, top_k * mult)

        try:
            return await db.search_rag_chunks(query_vec, limit)
        except Exception as e:
            logger.warning("[rag.docs] pgvector query failed, using in-memory vectors: %s", e)
            self._pg_store_disabled = True
            return []


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("[rag.docs] Skip %s: %s", path, e)
        return ""


_retriever: DocumentRetriever | None = None


def get_document_retriever() -> DocumentRetriever:
    global _retriever
    if _retriever is None:
        _retriever = DocumentRetriever()
    return _retriever


def reset_document_retriever() -> None:
    global _retriever
    _retriever = None
    _QUERY_RESULT_CACHE.clear()
