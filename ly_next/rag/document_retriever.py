from __future__ import annotations

import hashlib
from pathlib import Path

from ly_next.core.config import config, get_data_root, get_project_root
from ly_next.core.database import RAG_EMBEDDING_DIM, db
from ly_next.core.logger import get_logger
from ly_next.rag.chunking import chunk_text
from ly_next.rag.embedding_config import resolve_embedding_http_config
from ly_next.rag.embeddings import fetch_embeddings
from ly_next.rag.retrieval_fusion import bm25_rank, mmr_select_vectors, rrf_fuse
from ly_next.rag.similarity import cosine_similarity, jaccard_similarity

logger = get_logger(__name__)


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


class DocumentRetriever:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._sources: list[str] = []
        self._vectors: list[list[float]] | None = None
        self._loaded_path = ""
        self._pg_store_sig = ""
        self._pg_store_disabled = False
        self._warned_empty_path = False
        self._configured_once = False

    def configure(self) -> None:
        raw = str(config.get("agent.rag.documents_path", "") or "").strip()
        self._chunks = []
        self._sources = []
        self._vectors = None
        self._loaded_path = raw
        self._configured_once = True
        self._pg_store_sig = ""
        self._pg_store_disabled = False
        if not raw:
            if bool(config.get("agent.rag.enabled", False)) and not self._warned_empty_path:
                self._warned_empty_path = True
                logger.warning(
                    "[rag.docs] agent.rag.documents_path is empty; document retrieval is disabled."
                )
            return
        self._warned_empty_path = False

        target = _resolve_documents_path(raw)

        file_units: list[tuple[str, str]] = []
        if target.is_file():
            file_units.append((target.name, _read_file(target)))
        elif target.is_dir():
            for p in sorted(target.rglob("*")):
                if p.is_file() and p.suffix.lower() in {".md", ".txt", ".markdown"}:
                    try:
                        rel = str(p.relative_to(target))
                    except ValueError:
                        rel = p.name
                    file_units.append((rel, _read_file(p)))
        else:
            logger.warning("[rag.docs] Path not found: %s", target)

        chunk_size = int(config.get("agent.rag.chunk_size", 900) or 900)
        overlap = int(config.get("agent.rag.chunk_overlap", 120) or 120)
        for src_label, t in file_units:
            for c in chunk_text(t, chunk_size, overlap):
                if c:
                    self._chunks.append(c)
                    self._sources.append(src_label)

    async def retrieve_formatted(self, user_query: str) -> str:
        if not config.get("agent.rag.enabled", False):
            return ""
        path_cfg = str(config.get("agent.rag.documents_path", "") or "").strip()
        if not self._configured_once or self._loaded_path != path_cfg:
            self.configure()
        if not self._chunks or not user_query.strip():
            return ""

        top_k = int(config.get("agent.rag.top_k", 5) or 5)
        min_sim = float(config.get("agent.rag.min_similarity", 0.12) or 0.0)
        use_emb = bool(config.get("agent.rag.use_embeddings", True))
        hybrid = bool(config.get("agent.rag.hybrid_enabled", True))
        rrf_k = int(config.get("agent.rag.rrf_k", 60) or 60)
        mmr_on = bool(config.get("agent.rag.mmr_enabled", False))
        mmr_lambda = float(config.get("agent.rag.mmr_lambda", 0.55) or 0.55)
        mult = max(1, int(config.get("agent.rag.retrieve_multiplier", 3) or 3))
        show_src = bool(config.get("agent.rag.show_source", True))

        q_vec: list[float] | None = None
        ranked: list[tuple[float, str]] = []

        if use_emb:
            try:
                ranked, q_vec = await self._rank_embedding_with_query_vec(user_query)
            except Exception as e:
                msg = str(e).strip() or repr(e)
                logger.warning(
                    "[rag.docs] Embedding retrieve failed, fallback lexical (%s): %s",
                    type(e).__name__,
                    msg,
                )
                ranked = self._rank_lexical(user_query)
                q_vec = None
        else:
            ranked = self._rank_lexical(user_query)

        if hybrid and self._chunks:
            lex_bm25 = bm25_rank(user_query, self._chunks)
            lex_jac = self._rank_lexical(user_query)
            if use_emb and ranked:
                ranked = rrf_fuse([ranked, lex_bm25], k=rrf_k)
            else:
                ranked = rrf_fuse([lex_jac, lex_bm25], k=rrf_k)
            picked = ranked[:top_k]
        elif use_emb and ranked:
            picked = [(s, ch) for s, ch in ranked if s >= min_sim][:top_k]
            if not picked and ranked and ranked[0][0] > 0:
                picked = ranked[:1]
        else:
            picked = [(s, ch) for s, ch in ranked if s >= min_sim][:top_k]
            if not picked and ranked and ranked[0][0] > 0:
                picked = ranked[:1]

        if (
            mmr_on
            and q_vec
            and self._vectors
            and len(self._vectors) == len(self._chunks)
            and picked
        ):
            pool_n = min(len(ranked), top_k * mult)
            ranked_pool = ranked[:pool_n] if ranked else picked
            picked = mmr_select_vectors(
                ranked_pool,
                chunks=self._chunks,
                vectors=self._vectors,
                query_vec=q_vec,
                top_k=top_k,
                pool_size=top_k * mult,
                lambda_param=mmr_lambda,
                cosine_fn=cosine_similarity,
            )

        if not picked:
            return ""

        parts = []
        for i, (score, ch) in enumerate(picked, 1):
            src = ""
            if show_src and self._sources and self._chunks:
                try:
                    ix = self._chunks.index(ch)
                    if 0 <= ix < len(self._sources):
                        src = self._sources[ix]
                except ValueError:
                    src = ""
            head = f"片段{i}（相关度 {score:.3f}）"
            if src:
                head += f" · 来源 {src}"
            parts.append(f"{head}\n{ch}")
        return "\n\n---\n\n".join(parts)

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

        if self._vectors is None or len(self._vectors) != len(self._chunks):
            batch = 32
            all_vec: list[list[float]] = []
            for i in range(0, len(self._chunks), batch):
                sub = self._chunks[i : i + batch]
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
        h.update(str(len(self._chunks)).encode("utf-8"))
        if self._chunks:
            h.update(self._chunks[0][:400].encode("utf-8", errors="ignore"))
            h.update(self._chunks[-1][:400].encode("utf-8", errors="ignore"))
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
        mult = max(1, int(config.get("agent.rag.retrieve_multiplier", 3) or 3))
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
